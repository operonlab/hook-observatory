-- Failure attribution columns for multi-skill session analysis
ALTER TABLE anvil.invocations ADD COLUMN IF NOT EXISTS attribution_score FLOAT;
ALTER TABLE anvil.invocations ADD COLUMN IF NOT EXISTS attribution_reason TEXT;
