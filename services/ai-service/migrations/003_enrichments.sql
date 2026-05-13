-- Product enrichments owned by the AI service.
-- One row per product. Updated each time enrichment runs (re-running is safe).
-- The embedding lives in product_embeddings (from migration 001) — this
-- table holds the LLM-generated text fields and structured attributes.

CREATE TABLE IF NOT EXISTS product_enrichments (
  product_id        BIGINT PRIMARY KEY,
  -- LLM-generated marketing-quality description
  seo_description   TEXT,
  -- LLM-extracted structured attributes as JSON
  -- (e.g. {"color": "black", "wireless": true, "battery_hours": 8})
  attributes        JSONB,
  -- Model identifiers so we can detect stale enrichments when we swap models
  llm_model         TEXT NOT NULL,
  -- Status lets us track in-progress vs failed vs successful enrichments
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'success', 'failed')),
  last_error        TEXT,
  -- Idempotency: which event_id produced this enrichment
  source_event_id   TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_enrichments_status
  ON product_enrichments(status);

-- GIN index on attributes lets us query e.g. "products where attributes ->> 'color' = 'black'"
CREATE INDEX IF NOT EXISTS idx_product_enrichments_attrs
  ON product_enrichments USING GIN (attributes);
