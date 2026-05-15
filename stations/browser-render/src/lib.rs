//! Workshop browser-render — library surface for integration tests
//! and downstream Rust consumers.
//!
//! The binary entry point lives in `src/main.rs`. Everything in here is
//! exposed so `tests/smoke.rs` can drive the renderer in-process.

pub mod config;
pub mod flags;
pub mod manifest;
pub mod render;
