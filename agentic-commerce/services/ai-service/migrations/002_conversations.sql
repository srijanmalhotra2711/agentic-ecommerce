-- Conversation memory for the agentic shopping assistant.
-- Each session has an ordered list of turns (user message, assistant message,
-- tool calls, tool results). We store everything as JSONB so the schema can
-- evolve as we add new tools or fields without migrations.

CREATE TABLE IF NOT EXISTS conversations (
  id            BIGSERIAL PRIMARY KEY,
  session_id    TEXT        NOT NULL,
  user_id       BIGINT,
  role          TEXT        NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
  content       TEXT,
  tool_calls    JSONB,
  tool_call_id  TEXT,
  tool_name     TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_session
  ON conversations (session_id, created_at);

-- Pending order confirmations: when the LLM proposes an order, we store the
-- proposal here. The next user message either confirms or cancels.
-- We use a separate table (not a column on conversations) so we can clean
-- up unconfirmed proposals separately.
CREATE TABLE IF NOT EXISTS pending_orders (
  id           BIGSERIAL PRIMARY KEY,
  session_id   TEXT        NOT NULL UNIQUE,  -- one pending per session at a time
  user_id      BIGINT      NOT NULL,
  items        JSONB       NOT NULL,
  total_amount NUMERIC(10,2) NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at   TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '15 minutes')
);
