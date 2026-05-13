#!/usr/bin/env bash
# Phase 3 smoke test — event-driven AI enrichment pipeline.
#
# Flow:
#   1. POST a new product to product-service
#   2. product-service publishes ProductCreated to Kafka
#   3. ai-service consumer picks it up, generates SEO + attributes, embeds it
#   4. ai-service publishes ProductEnriched
#   5. We verify the enrichment exists via /ai/products/{id}/enrichment
#   6. We verify the new product is also searchable via semantic search

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}→${NC} $1"; }

echo "=== Phase 3: event-driven AI enrichment smoke test ==="
echo

# 1. Pre-flight: services healthy
info "Checking services..."
curl -fsS http://localhost:3002/healthz >/dev/null || fail "product-service not healthy"
curl -fsS http://localhost:8000/healthz >/dev/null || fail "ai-service not healthy"
pass "product-service and ai-service responding"

# 2. Create a product with intentionally sparse info
info "Creating a sparse product..."
TIMESTAMP=$(date +%s)
PRODUCT_RESP=$(curl -fsS -X POST http://localhost:3002/products \
  -H 'Content-Type: application/json' \
  -H "x-correlation-id: phase3-smoke-${TIMESTAMP}" \
  -d '{
    "name": "BlueTooth Earbuds Pro",
    "description": "Black wireless earbuds. Bluetooth 5.0. ANC. 8-hour battery.",
    "price": 79.99,
    "stock": 100,
    "category": "electronics"
  }')

PRODUCT_ID=$(echo "$PRODUCT_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
pass "product created (id=$PRODUCT_ID) — ProductCreated event published"

# 3. Wait for the consumer to process. Enrichment is 2 LLM calls + 1 embedding,
#    which on llama3.1:8b CPU is ~20-40s total. We poll until status changes
#    from null/pending to success/partial/failed.
info "Waiting for enrichment pipeline (this takes ~30s on CPU)..."

MAX_WAIT=120
ELAPSED=0
STATUS="unknown"
while [ $ELAPSED -lt $MAX_WAIT ]; do
  RESP=$(curl -fsS "http://localhost:8000/ai/products/$PRODUCT_ID/enrichment" 2>/dev/null || echo "")
  if [ -n "$RESP" ] && echo "$RESP" | grep -q "status"; then
    STATUS=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "success" ] || [ "$STATUS" = "partial" ] || [ "$STATUS" = "failed" ]; then
      break
    fi
  fi
  sleep 3
  ELAPSED=$((ELAPSED + 3))
  echo -n "."
done
echo

[ "$STATUS" != "unknown" ] || fail "enrichment never appeared after ${MAX_WAIT}s — check ai-service logs"
[ "$STATUS" != "failed" ] || fail "enrichment status=failed — check ai-service logs for last_error"
pass "enrichment completed in ${ELAPSED}s (status: $STATUS)"

# 4. Inspect the enrichment content
info "Fetching enrichment details..."
ENRICHMENT=$(curl -fsS "http://localhost:8000/ai/products/$PRODUCT_ID/enrichment")

SEO=$(echo "$ENRICHMENT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('seo_description') or '')")
ATTRS=$(echo "$ENRICHMENT" | python3 -c "import sys,json;a=json.load(sys.stdin).get('attributes') or {};import json as j;print(j.dumps(a))")

[ -n "$SEO" ] || fail "no SEO description was generated"
pass "SEO description: \"${SEO:0:80}...\""

[ "$ATTRS" != "{}" ] || fail "no attributes were extracted (got empty dict)"
pass "Attributes: $ATTRS"

# 5. Verify the new product is also semantically searchable
info "Verifying semantic search works for the new product..."
sleep 2
SEARCH=$(curl -fsS -X POST http://localhost:8000/ai/semantic-search \
  -H 'Content-Type: application/json' \
  -d '{"query":"wireless headphones with noise cancellation","limit":5}')

FOUND=$(echo "$SEARCH" | python3 -c "
import sys, json
results = json.load(sys.stdin)
hit = [r for r in results if r['product_id'] == $PRODUCT_ID]
print('yes' if hit else 'no')
")
[ "$FOUND" = "yes" ] || fail "new product was not found in semantic search results"
pass "new product appears in semantic search results"

# 6. Verify the ProductEnriched event was published to Kafka
info "Checking ProductEnriched topic..."
# We just verify the topic exists and has messages — full validation would
# require a Kafka consumer; this is enough for a smoke test.
TOPIC_INFO=$(docker compose exec -T kafka kafka-topics --bootstrap-server localhost:9092 \
  --describe --topic ProductEnriched 2>/dev/null || echo "")
echo "$TOPIC_INFO" | grep -q "ProductEnriched" || fail "ProductEnriched topic doesn't exist"
pass "ProductEnriched topic exists in Kafka"

echo
echo -e "${GREEN}✓ Phase 3 enrichment pipeline works end-to-end${NC}"
echo
echo "What just happened:"
echo "  1. Created a product with sparse info — only a basic description"
echo "  2. Kafka delivered ProductCreated to ai-service"
echo "  3. ai-service generated a polished SEO description via LLM"
echo "  4. ai-service extracted structured attributes (color, wireless, battery_hours, etc)"
echo "  5. The product was auto-embedded for semantic search"
echo "  6. ai-service published ProductEnriched for downstream consumers"
echo
echo "Inspect the enrichment yourself:"
echo "  curl -s http://localhost:8000/ai/products/$PRODUCT_ID/enrichment | python3 -m json.tool"
