-- Rename agentops schema to agent_metrics
-- Applied manually: psql -h localhost -U joneshong -d workshop -f 002_rename_schema.sql

ALTER SCHEMA agentops RENAME TO agent_metrics;
