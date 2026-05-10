#!/usr/bin/env bash
# Verifies the whole stack works end-to-end.
# Run after `docker compose up -d` and after `scripts/pull-ollama-models.sh`.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}→${NC} $1"; }

echo "=== agentic-commerce smoke test ==="
echo

# 1. Health checks
info "Health checks..."
curl -fsS http://localhost:3001/healthz >/dev/null || fail "user-service unhealthy"
pass "user-service /healthz"
curl -fsS http://localhost:3002/healthz >/dev/null || fail "product-service unhealthy"
pass "product-service /healthz"
curl -fsS http://localhost:3003/healthz >/dev/null || fail "order-service unhealthy"
pass "order-service /healthz"
curl -fsS http://localhost:8000/healthz >/dev/null || fail "ai-service unhealthy"
pass "ai-service /healthz"

# 2. Readiness (deeper — checks DB and Kafka)
info "Readiness checks..."
curl -fsS http://localhost:3001/readyz >/dev/null || fail "user-service not ready"
pass "user-service /readyz"
curl -fsS http://localhost:8000/readyz >/dev/null || fail "ai-service not ready (Ollama up?)"
pass "ai-service /readyz (DB + Ollama reachable)"

# 3. Register a user
info "Registering test user..."
REG_RESP=$(curl -fsS -X POST http://localhost:3001/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@test.dev","password":"smoketest123","name":"Smoke"}' || true)
if [ -z "$REG_RESP" ]; then
  info "User may already exist, continuing"
fi

LOGIN_RESP=$(curl -fsS -X POST http://localhost:3001/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@test.dev","password":"smoketest123"}')
TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
USER_ID=$(echo "$LOGIN_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['user']['id'])")
pass "user logged in (id=$USER_ID)"

# 4. Verify product seed data is present
info "Listing products..."
PRODUCTS=$(curl -fsS http://localhost:3002/products)
PRODUCT_COUNT=$(echo "$PRODUCTS" | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
[ "$PRODUCT_COUNT" -ge 5 ] || fail "expected >= 5 seeded products, got $PRODUCT_COUNT"
PRODUCT_ID=$(echo "$PRODUCTS" | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
pass "$PRODUCT_COUNT products available (using id=$PRODUCT_ID for order test)"

# 5. Create an order — exercises product-service call + outbox
info "Creating order..."
ORDER_RESP=$(curl -fsS -X POST http://localhost:3003/orders \
  -H 'Content-Type: application/json' \
  -H 'x-correlation-id: smoke-test-001' \
  -d "{\"user_id\":$USER_ID,\"items\":[{\"product_id\":$PRODUCT_ID,\"quantity\":2}]}")
ORDER_ID=$(echo "$ORDER_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['order_id'])")
TOTAL=$(echo "$ORDER_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['total_amount'])")
pass "order created (id=$ORDER_ID, total=\$$TOTAL)"

# 6. Verify outbox event was published (poller picks it up within ~1s)
info "Waiting for outbox poller..."
sleep 2
PUBLISHED=$(docker compose exec -T pg-orders psql -U postgres -d orders_db -tAc \
  "SELECT COUNT(*) FROM event_outbox WHERE published_at IS NOT NULL AND correlation_id='smoke-test-001';")
[ "$PUBLISHED" -ge 1 ] || fail "outbox event was not published within 2s"
pass "outbox event published with correlation_id=smoke-test-001"

# 7. Wait for AI service to embed the seed products
#    (these embed at startup as ProductCreated events flow through Kafka,
#    OR we re-trigger them here if the consumer started after products were seeded)
info "Embedding seed products (manual trigger to ensure consistency)..."
for pid in $(echo "$PRODUCTS" | python3 -c "import sys,json;[print(p['id']) for p in json.load(sys.stdin)]"); do
  PRODUCT=$(echo "$PRODUCTS" | python3 -c "
import sys,json
ps=json.load(sys.stdin)
p=next(p for p in ps if p['id']==$pid)
import urllib.parse
print(json.dumps({'product_id':p['id'],'name':p['name'],'description':p['description'],'category':p['category']}))
")
  curl -fsS -X POST http://localhost:8000/ai/embed-product \
    -H 'Content-Type: application/json' \
    -d "$PRODUCT" >/dev/null
done
pass "all seed products embedded"

# 8. Run a semantic search
info "Running semantic search..."
SEARCH_RESP=$(curl -fsS -X POST http://localhost:8000/ai/semantic-search \
  -H 'Content-Type: application/json' \
  -d '{"query":"quiet keyboard for typing","limit":3}')
TOP_NAME=$(echo "$SEARCH_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['name'])")
pass "semantic search returned top match: $TOP_NAME"

echo
echo -e "${GREEN}✓ All smoke tests passed${NC}"
echo
echo "Try these:"
echo "  curl http://localhost:3002/products"
echo "  curl -X POST http://localhost:8000/ai/semantic-search -H 'Content-Type: application/json' -d '{\"query\":\"morning beverage\"}'"
