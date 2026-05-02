//! system-monitor-rs library root.
//!
//! Modules mirror the original Python layout in `stations/system-monitor/`
//! (collector.py, api.py, memory_guardian.py, reporter.py, ...) to make
//! file-by-file porting reviewable.

pub mod api;
pub mod collector;
pub mod config;
pub mod disk_manager;
pub mod guardian;
pub mod notifier;
pub mod reporter;
pub mod scheduler;
pub mod shared;
pub mod store;
pub mod tmux_status;
