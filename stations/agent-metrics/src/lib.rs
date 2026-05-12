//! agent-metrics-rs — library entry point.
//!
//! Modules are introduced phase-by-phase:
//!   Phase 1: config, db
//!   Phase 2: sysmon, proc_query, store, guardian, sweep, loops
//!   Phase 3: collectors (litellm, usage, quota-shim)
//!   Phase 4: web (axum routes + templates)
//!   Phase 5: engines (maestro, task_manager)

pub mod config;
pub mod db;

pub mod sysmon;
pub mod proc_query;
pub mod store;
pub mod guardian;
pub mod sweep;
pub mod loops;

pub mod collectors;

pub mod aggregator;
pub mod engines;
pub mod session;
pub mod web;
