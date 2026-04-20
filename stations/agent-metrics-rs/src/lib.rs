//! agent-metrics-rs — library entry point.
//!
//! Modules are introduced phase-by-phase:
//!   Phase 1: config, db
//!   Phase 2: sysmon, guardian, sweep (process-monitoring loops)
//!   Phase 3: collectors (litellm, usage, quota)
//!   Phase 4: web (axum routes + templates)
//!   Phase 5: engines (maestro, task_manager)

pub mod config;
pub mod db;
