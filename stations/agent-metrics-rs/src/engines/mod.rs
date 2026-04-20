//! Phase 5b-1: maestro orchestration engine + task_manager.
//!
//! Faithfully ports `engines/maestro.py` + `engines/task_manager.py` to Rust.
//! The dispatch layer shells out to existing CLI runners (claude_headless.py,
//! codex_headless.py, gemini_headless.py) so we don't re-derive the
//! per-CLI argument shape.

pub mod dispatch;
pub mod routing;
pub mod runs;
pub mod tasks;
