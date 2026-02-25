CREATE TABLE IF NOT EXISTS layout_versions (
  id SERIAL PRIMARY KEY,
  layout_name VARCHAR(100) NOT NULL DEFAULT 'default',
  version INT NOT NULL,
  grid_width INT NOT NULL,
  grid_height INT NOT NULL,
  furniture JSONB NOT NULL,
  seats JSONB NOT NULL,
  rest_zone JSONB NOT NULL,
  door_x INT NOT NULL,
  door_y INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(layout_name, version)
);

CREATE INDEX IF NOT EXISTS idx_layout_versions_latest
  ON layout_versions(layout_name, version DESC);
