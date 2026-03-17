-- Add time-saved tracking columns to anvil.invocations
-- Source: 蠶食評估 畠山謙人案例 — time-saved ROI tracking pattern

ALTER TABLE anvil.invocations ADD COLUMN IF NOT EXISTS manual_estimate_minutes FLOAT;
ALTER TABLE anvil.invocations ADD COLUMN IF NOT EXISTS time_saved_minutes FLOAT;

COMMENT ON COLUMN anvil.invocations.manual_estimate_minutes IS 'Estimated manual time in minutes for this task';
COMMENT ON COLUMN anvil.invocations.time_saved_minutes IS 'Time saved = manual_estimate - (duration_ms / 60000)';
