CREATE TABLE IF NOT EXISTS products (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT          NOT NULL,
  description TEXT          NOT NULL DEFAULT '',
  price       NUMERIC(10,2) NOT NULL CHECK (price >= 0),
  stock       INTEGER       NOT NULL DEFAULT 0 CHECK (stock >= 0),
  category    TEXT          NOT NULL DEFAULT 'general',
  created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);

-- Seed a few products so smoke tests work out of the box
INSERT INTO products (name, description, price, stock, category) VALUES
  ('Mechanical Keyboard', 'Hot-swappable keyboard with linear switches, ideal for quiet typing', 129.99, 50, 'electronics'),
  ('Wireless Mouse', 'Ergonomic wireless mouse with adjustable DPI', 39.99, 200, 'electronics'),
  ('Standing Desk', 'Electric height-adjustable standing desk, 60x30 inches', 449.00, 15, 'furniture'),
  ('Coffee Beans', 'Single-origin Ethiopian coffee, medium roast, 1lb bag', 18.50, 100, 'grocery'),
  ('Yoga Mat', 'Non-slip yoga mat with carrying strap', 29.99, 80, 'fitness')
ON CONFLICT DO NOTHING;
