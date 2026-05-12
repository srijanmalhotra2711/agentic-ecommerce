# agentic-commerce

E-commerce microservices platform with **agentic AI** at its core: semantic product search powered by local LLMs and event-driven AI enrichment integrated into a distributed event mesh.

This isn't a chatbot bolted onto a REST API. The AI service is a first-class citizen in the architecture — consuming `ProductCreated` events to auto-generate embeddings, exposing semantic search via pgvector, and laying the groundwork for an agentic shopping assistant that orchestrates the other services through tool-calling.

## Architecture

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐
│  user-   │    │ product- │    │  order-  │    │  ai-service  │
│ service  │    │ service  │    │ service  │    │  (Python)    │
│   (TS)   │    │   (TS)   │    │   (TS)   │    │              │
└────┬─────┘    └────┬─────┘    └────┬─────┘    └──────┬───────┘
     │               │               │                 │
     │           ┌───▼───────────────▼───┐         ┌───▼────┐
     │           │      Apache Kafka     │◄────────┤ Ollama │
     │           │     (event bus)       │         │ (LLM + │
     │           └───────────┬───────────┘         │ embed) │
     │                       │                     └────────┘
     ▼                       ▼                         │
 pg-users              pg-products                     ▼
                       pg-orders                   pg-ai (pgvector)
```

**Languages:**
- TypeScript (Node 20) for user/product/order — strict mode, full type safety
- Python 3.12 (FastAPI) for ai-service — the AI/ML ecosystem standard

**Why polyglot?** Each service uses the language and ecosystem best suited to its domain. Splitting at clean boundaries demonstrates real microservices reasoning, not "everything in Node because the tutorial said so."

## Engineering features

- **Transactional outbox** in order-service for guaranteed at-least-once event publishing (no lost events when the process crashes between DB commit and Kafka publish)
- **Correlation IDs** propagated through HTTP headers and Kafka message headers, with `AsyncLocalStorage` (Node) and `ContextVar` (Python) wiring them automatically into every log line
- **Structured JSON logging** (Pino + structlog) with redaction of credentials
- **Liveness vs readiness** distinction — liveness restarts the pod, readiness only de-registers it from the load balancer
- **Graceful shutdown** drains in-flight requests, commits Kafka offsets, closes DB pools
- **Multi-stage Docker builds** producing ~150MB images, running as non-root
- **Healthchecks** on every container with `condition: service_healthy` in compose so startup ordering is deterministic
- **Env validation** at startup via Zod (TS) / Pydantic (Py) — service refuses to boot with bad config
- **pgvector** for semantic search at scale, with cosine-similarity IVFFlat index
- **Event-driven AI**: `ProductCreated` → ai-service consumer → embedding generated → stored in pgvector

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend (CRUD) | Node 20 + TypeScript + Express | Type safety with the JS ecosystem reach |
| Backend (AI) | Python 3.12 + FastAPI | All AI/ML tooling lives here |
| Event bus | Apache Kafka | Industry standard, exactly-once with idempotent producer |
| Databases | Postgres 16 (per service) | One DB per service is the textbook microservices boundary |
| Vector store | pgvector | Reuses Postgres, no separate vector DB to operate |
| LLM | Ollama (local) — `llama3.2:3b` | Free, no API keys, demonstrates self-hosted ML serving |
| Embeddings | Ollama — `nomic-embed-text` (768d) | Open-source, fast, runs on CPU |
| Container | Docker + docker-compose | Local dev parity with K8s deploy targets |

## Quick start

### Prerequisites
- Docker Desktop (allocate at least 6GB RAM — Ollama models need it)
- A reasonably modern Mac/Linux machine; Ollama can run on Windows but isn't tested here

### One-time setup
```bash
# 1. Build all services
docker compose build

# 2. Bring up infrastructure first (Postgres, Kafka, Ollama)
docker compose up -d zookeeper pg-users pg-products pg-orders pg-ai
docker compose up -d kafka ollama

# 3. Wait for Kafka and Ollama to be healthy (~30 seconds)
docker compose ps   # look for "(healthy)" status

# 4. Pull the Ollama models (one-time, ~2.3GB total)
./scripts/pull-ollama-models.sh

# 5. Start application services
docker compose up -d user-service product-service order-service ai-service
```

### Verify everything works
```bash
./scripts/smoke-test.sh
```
Expected output: a green checklist of 8 passing tests, ending with a real semantic search result.

### Try it manually
```bash
# Register and log in
curl -X POST http://localhost:3001/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","password":"password123","name":"Alice"}'

curl -X POST http://localhost:3001/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","password":"password123"}'

# List seeded products
curl http://localhost:3002/products

# Semantic search — natural language!
curl -X POST http://localhost:8000/ai/semantic-search \
  -H 'Content-Type: application/json' \
  -d '{"query":"something quiet to type on","limit":3}'

# Place an order — exercises product fetch + outbox pattern
curl -X POST http://localhost:3003/orders \
  -H 'Content-Type: application/json' \
  -d '{"user_id":1,"items":[{"product_id":1,"quantity":2}]}'
```

## Project layout

```
.
├── docker-compose.yml          # 4 services + 4 Postgres + Kafka + Ollama
├── package.json                # npm workspaces root (TypeScript services)
├── shared/
│   └── common/                 # @agentic-commerce/common — TS shared lib
│       └── src/
│           ├── logger/         # Pino with redaction + correlation
│           ├── correlation/    # AsyncLocalStorage propagation
│           ├── kafka/          # Producer + consumer with header wiring
│           ├── health/         # /healthz and /readyz with shutdown gating
│           ├── shutdown/       # SIGTERM-aware drain
│           ├── env/            # Zod-based fail-fast validation
│           └── errors/         # Typed errors + Express middleware
├── services/
│   ├── user-service/           # Auth: register/login + JWT
│   ├── product-service/        # Catalog CRUD, publishes ProductCreated
│   ├── order-service/          # Orders + transactional outbox
│   └── ai-service/             # Python: embeddings, semantic search,
│       │                       # event consumer, future agentic chat
│       ├── app/
│       │   ├── main.py
│       │   ├── routers/        # FastAPI routers (health, search, chat)
│       │   ├── services/       # Embeddings, Ollama client
│       │   ├── events/         # Kafka consumer
│       │   └── db/             # asyncpg pool
│       └── migrations/         # pgvector setup
└── scripts/
    ├── smoke-test.sh           # End-to-end check
    └── pull-ollama-models.sh   # First-time Ollama model download
```

## Roadmap

This repo is built incrementally. The current state is **Phase 1**.

| Phase | Feature | Status |
|---|---|---|
| 1 | Foundation: 4 services, shared lib, outbox, semantic search | ✅ Done |
| 2 | Agentic shopping assistant — LLM with tool-calling | ⏳ Next |
| 3 | Event-driven AI enrichment (auto SEO descriptions, attributes) | ⏳ |
| 4 | Saga compensating actions for failed orders | ⏳ |
| 5 | OpenTelemetry distributed tracing → Jaeger | ⏳ |
| 6 | Kubernetes manifests + minimal frontend | ⏳ |

## Resume bullets earned by this repo

- *"Designed a 4-service e-commerce platform with TypeScript and Python, integrating a local-LLM-backed AI service for semantic search via pgvector embeddings (768-dim, cosine similarity)."*
- *"Implemented the transactional outbox pattern in the order service, guaranteeing at-least-once event publication across the Kafka event mesh."*
- *"Built end-to-end correlation ID propagation across HTTP and Kafka boundaries using `AsyncLocalStorage` and Python `ContextVar`, enabling distributed tracing via structured logs alone."*
- *"Containerized 4 services with multi-stage Docker builds, non-root users, and HTTP healthchecks; orchestrated with docker-compose using `condition: service_healthy` for deterministic startup."*

## License
MIT — portfolio project, use however you like.
