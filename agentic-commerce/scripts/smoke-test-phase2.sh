#!/usr/bin/env bash
# Phase 2 smoke test — agentic shopping assistant.
# Prerequisites: phase 1 smoke-test passes; products are embedded.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}→${NC} $1"; }

SESSION="phase2-smoke-$(date +%s)"
USER_ID=1

echo "=== Phase 2: agentic shopping assistant smoke test ==="
echo "Session: $SESSION"
echo

# 1. Ask the agent for a recommendation
info "Turn 1: asking for a recommendation..."
RESP1=$(curl -fsS -X POST http://localhost:8000/ai/chat \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":$USER_ID,\"session_id\":\"$SESSION\",\"message\":\"I'm looking for something quiet to type on, budget around \$150\"}")

echo "Reply:"
echo "$RESP1" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  '+d['reply'].replace(chr(10),chr(10)+'  '));print();print('  Tool calls:',', '.join(t['name'] for t in d['tool_calls_executed']) or '(none)')"
echo

TOOL_NAMES=$(echo "$RESP1" | python3 -c "import sys,json;print(' '.join(t['name'] for t in json.load(sys.stdin)['tool_calls_executed']))")
echo "$TOOL_NAMES" | grep -q "semantic_search_products" || fail "expected agent to call semantic_search_products"
pass "agent called semantic_search_products"

# 2. Ask the agent to propose an order
info "Turn 2: asking to order it..."
RESP2=$(curl -fsS -X POST http://localhost:8000/ai/chat \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":$USER_ID,\"session_id\":\"$SESSION\",\"message\":\"Great, please order one of those\"}")

echo "Reply:"
echo "$RESP2" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  '+d['reply'].replace(chr(10),chr(10)+'  '));print();print('  Tool calls:',', '.join(t['name'] for t in d['tool_calls_executed']) or '(none)')"
echo

TOOL_NAMES2=$(echo "$RESP2" | python3 -c "import sys,json;print(' '.join(t['name'] for t in json.load(sys.stdin)['tool_calls_executed']))")
echo "$TOOL_NAMES2" | grep -q "propose_order" || fail "expected agent to call propose_order"
echo "$TOOL_NAMES2" | grep -q "confirm_order" && fail "agent should NOT have called confirm_order without user confirmation"
pass "agent proposed the order WITHOUT confirming (safety gate working)"

# Verify there's a pending order in the DB
PENDING=$(docker compose exec -T pg-ai psql -U postgres -d ai_db -tAc \
  "SELECT total_amount FROM pending_orders WHERE session_id='$SESSION';")
[ -n "$PENDING" ] || fail "no pending order found in DB"
pass "pending order persisted (total: \$$PENDING)"

# 3. Confirm the order
info "Turn 3: confirming the order..."
RESP3=$(curl -fsS -X POST http://localhost:8000/ai/chat \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":$USER_ID,\"session_id\":\"$SESSION\",\"message\":\"yes, confirm it\"}")

echo "Reply:"
echo "$RESP3" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  '+d['reply'].replace(chr(10),chr(10)+'  '));print();print('  Tool calls:',', '.join(t['name'] for t in d['tool_calls_executed']) or '(none)')"
echo

TOOL_NAMES3=$(echo "$RESP3" | python3 -c "import sys,json;print(' '.join(t['name'] for t in json.load(sys.stdin)['tool_calls_executed']))")
echo "$TOOL_NAMES3" | grep -q "confirm_order" || fail "expected agent to call confirm_order"
pass "agent called confirm_order on user confirmation"

# Verify a real order was created in order-service's DB
ORDER_COUNT=$(docker compose exec -T pg-orders psql -U postgres -d orders_db -tAc \
  "SELECT COUNT(*) FROM orders WHERE user_id=$USER_ID;")
[ "$ORDER_COUNT" -ge 1 ] || fail "no orders in pg-orders for user $USER_ID"
pass "real order created in order-service DB (count: $ORDER_COUNT)"

# Verify pending was cleared
PENDING2=$(docker compose exec -T pg-ai psql -U postgres -d ai_db -tAc \
  "SELECT COUNT(*) FROM pending_orders WHERE session_id='$SESSION';")
[ "$PENDING2" = "0" ] || fail "pending order should have been cleared after confirmation"
pass "pending order cleared after confirmation"

# Verify conversation history is persisted
TURNS=$(docker compose exec -T pg-ai psql -U postgres -d ai_db -tAc \
  "SELECT COUNT(*) FROM conversations WHERE session_id='$SESSION';")
[ "$TURNS" -ge 6 ] || fail "expected >= 6 conversation turns persisted, got $TURNS"
pass "conversation history persisted ($TURNS turns)"

echo
echo -e "${GREEN}✓ Phase 2 agentic flow works end-to-end${NC}"
echo
echo "What just happened:"
echo "  1. The LLM searched products semantically based on a vague description"
echo "  2. The LLM proposed an order WITHOUT placing it (safety gate)"
echo "  3. The LLM placed the real order ONLY after explicit user confirmation"
echo "  4. All conversation state and pending orders are durable in Postgres"
