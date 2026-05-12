CREATE TABLE IF NOT EXISTS orders (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT        NOT NULL,
  total_amount  NUMERIC(10,2) NOT NULL,
  status        TEXT          NOT NULL DEFAULT 'pending',
  failure_reason TEXT,
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
  id           BIGSERIAL PRIMARY KEY,
  order_id     BIGINT        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id   BIGINT        NOT NULL,
  product_name TEXT          NOT NULL,
  quantity     INTEGER       NOT NULL CHECK (quantity > 0),
  unit_price   NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);

CREATE TABLE IF NOT EXISTS event_outbox (
  id             BIGSERIAL PRIMARY KEY,
  aggregate_id   BIGINT      NOT NULL,
  event_type     TEXT        NOT NULL,
  payload        JSONB       NOT NULL,
  correlation_id TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  published_at   TIMESTAMPTZ,
  attempts       INTEGER     NOT NULL DEFAULT 0,
  last_error     TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_outbox_unpublished
  ON event_outbox (created_at)
  WHERE published_at IS NULL;
