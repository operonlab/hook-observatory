-- Workshop schema-per-module initialization
-- Each core module gets its own schema for data isolation.
-- Matches the 10 core modules defined in docs/architecture/.

-- Core Modules (Phase 1-3)
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS taskflow;
CREATE SCHEMA IF NOT EXISTS ideagraph;
CREATE SCHEMA IF NOT EXISTS admin;
CREATE SCHEMA IF NOT EXISTS intelflow;
CREATE SCHEMA IF NOT EXISTS memvault;
CREATE SCHEMA IF NOT EXISTS skillpath;
CREATE SCHEMA IF NOT EXISTS workpool;
CREATE SCHEMA IF NOT EXISTS matchcore;

-- Stations (standalone tools that need DB)
CREATE SCHEMA IF NOT EXISTS sysmon;
