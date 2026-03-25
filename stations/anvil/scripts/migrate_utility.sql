-- Memento-Skills utility tracking: per-skill execution success rate
-- U(s) = n_succ / (n_succ + n_fail)
-- Run: psql -f stations/anvil/scripts/migrate_utility.sql

ALTER TABLE anvil.skills ADD COLUMN IF NOT EXISTS utility_score FLOAT;
ALTER TABLE anvil.skills ADD COLUMN IF NOT EXISTS utility_n_succ INTEGER NOT NULL DEFAULT 0;
ALTER TABLE anvil.skills ADD COLUMN IF NOT EXISTS utility_n_fail INTEGER NOT NULL DEFAULT 0;
ALTER TABLE anvil.skills ADD COLUMN IF NOT EXISTS utility_updated_at TIMESTAMPTZ;
