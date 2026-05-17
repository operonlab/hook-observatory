//! Workshop unified logger — JSON output aligned to schemas/log-event.schema.json.
//!
//! # Usage
//!
//! ```ignore
//! #[tokio::main]
//! async fn main() {
//!     let _guard = workshop_log::init("sentinel");
//!     tracing::info!(method = "GET", path = "/health", "request_end");
//! }
//! ```
//!
//! With axum middleware (feature = "axum-middleware"):
//!
//! ```ignore
//! let app = Router::new()
//!     .route("/health", get(health))
//!     .layer(workshop_log::middleware::request_id_layer());
//! ```

use std::path::PathBuf;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

mod formatter;
pub use formatter::WorkshopJsonLayer;

#[cfg(feature = "axum-middleware")]
pub mod middleware;

/// Initialise the global tracing subscriber.
///
/// - Writes JSON-formatted logs (aligned to the Workshop log-event schema) to
///   `/opt/homebrew/var/log/workshop/<service>/general.log.YYYY-MM-DD` (rolling daily).
/// - Keeps at most 7 daily files; older ones are auto-purged by tracing-appender.
/// - Also writes a compact human-readable stream to stderr.
/// - Respects the `RUST_LOG` environment variable.
///
/// Returns a [`WorkerGuard`] that must be held for the lifetime of the process;
/// dropping it flushes the async log writer.
pub fn init(service: &'static str) -> WorkerGuard {
    let log_dir = PathBuf::from("/opt/homebrew/var/log/workshop").join(service);
    std::fs::create_dir_all(&log_dir).ok();

    let file_appender = tracing_appender::rolling::Builder::new()
        .rotation(tracing_appender::rolling::Rotation::DAILY)
        .filename_prefix("general")
        .filename_suffix("log")
        .max_log_files(7)
        .build(&log_dir)
        .expect("failed to build rolling file appender");
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

    let json_layer = WorkshopJsonLayer::new(service, non_blocking);
    let stderr_layer = fmt::layer().with_writer(std::io::stderr).compact();

    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    tracing_subscriber::registry()
        .with(filter)
        .with(json_layer)
        .with(stderr_layer)
        .init();

    guard
}
