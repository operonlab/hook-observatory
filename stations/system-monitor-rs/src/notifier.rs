//! Multi-channel notifications: file (jsonl) + macOS desktop + Redis pub/sub.
//!
//! Mirrors the Python `notifier.py` (PressureNotifier) dispatch layer, but
//! takes a generic `payload` (already-formatted alert JSON) instead of raw
//! collector data — escalation/level-rank logic stays in the caller.
//!
//! Payload schema (informal):
//! ```json
//! {
//!   "level":     "warning" | "critical",
//!   "title":     "...",
//!   "message":   "...",
//!   "timestamp": "2026-05-01T12:34:56+00:00",   // ISO-8601 (optional, auto-filled)
//!   "details":   { ... }                          // optional, free-form
//! }
//! ```
//!
//! Three sinks, each best-effort and independent — a failure in one does not
//! short-circuit the others.

use anyhow::{Context, Result};
use chrono::Utc;
use serde_json::{json, Value};
use std::path::PathBuf;
use tokio::io::AsyncWriteExt;

use crate::config::Settings;
use crate::shared::paths::alerts_dir;

const REDIS_CHANNEL: &str = "workshop:notifications:system-monitor";
const NOTIFY_TITLE: &str = "system-monitor";

/// Dispatch an alert payload to file (jsonl), macOS desktop notification,
/// and Redis pub/sub when a `redis_url` is configured.
pub async fn notify(cfg: &Settings, payload: &Value) -> Result<()> {
    // Normalize: ensure timestamp present.
    let mut owned = payload.clone();
    let timestamp = owned
        .get("timestamp")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| Utc::now().to_rfc3339());
    if let Some(obj) = owned.as_object_mut() {
        obj.entry("timestamp")
            .or_insert(Value::String(timestamp.clone()));
    }

    // 1) File sink (always on) — append jsonl per timestamped file.
    if let Err(e) = write_file_alert(cfg, &owned, &timestamp).await {
        tracing::warn!("notifier: file sink failed: {e}");
    }

    // 2) macOS desktop notification — terminal-notifier → osascript fallback.
    if let Err(e) = post_macos_notification(&owned).await {
        tracing::warn!("notifier: macOS notification failed: {e}");
    }

    // 3) Redis pub/sub — only when configured.
    if let Some(url) = cfg.redis_url.as_deref() {
        if let Err(e) = publish_redis(url, &owned).await {
            tracing::warn!("notifier: redis publish failed: {e}");
        }
    }

    Ok(())
}

/// Append/write an alert JSON file using the same `alert-{stamp}.json`
/// naming the Python notifier produces. Uses `:` → `-` so the filename
/// is portable across filesystems (e.g. exFAT on external drives).
async fn write_file_alert(cfg: &Settings, payload: &Value, timestamp: &str) -> Result<()> {
    let dir: PathBuf = alerts_dir(cfg);
    tokio::fs::create_dir_all(&dir)
        .await
        .with_context(|| format!("create alerts dir {}", dir.display()))?;

    let safe_stamp = timestamp.replace(':', "-");
    let path = dir.join(format!("alert-{safe_stamp}.json"));

    // Append-friendly: jsonl line.
    let mut line = serde_json::to_string(payload)?;
    line.push('\n');

    let mut file = tokio::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .await
        .with_context(|| format!("open alert file {}", path.display()))?;
    file.write_all(line.as_bytes()).await?;
    file.flush().await?;
    Ok(())
}

/// macOS: prefer `terminal-notifier` (richer styling), fall back to `osascript`.
async fn post_macos_notification(payload: &Value) -> Result<()> {
    let title = payload
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or(NOTIFY_TITLE);
    let message = payload
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if message.is_empty() {
        return Ok(());
    }

    if which("terminal-notifier") {
        let status = tokio::process::Command::new("terminal-notifier")
            .args([
                "-title",
                title,
                "-message",
                message,
                "-group",
                "system-monitor",
            ])
            .status()
            .await;
        if let Ok(s) = status {
            if s.success() {
                return Ok(());
            }
        }
    }

    // Fallback: osascript. Escape backslashes and quotes the same way Python does.
    let safe_msg = message.replace('\\', "\\\\").replace('"', "\\\"");
    let safe_title = title.replace('\\', "\\\\").replace('"', "\\\"");
    let script = format!(
        r#"display notification "{safe_msg}" with title "{safe_title}""#
    );
    let _ = tokio::process::Command::new("osascript")
        .args(["-e", &script])
        .status()
        .await;
    Ok(())
}

async fn publish_redis(url: &str, payload: &Value) -> Result<()> {
    let client = redis::Client::open(url).context("redis::Client::open")?;
    let mut conn = client
        .get_multiplexed_async_connection()
        .await
        .context("redis async connection")?;
    let body = serde_json::to_string(payload)?;
    let _: i64 = redis::cmd("PUBLISH")
        .arg(REDIS_CHANNEL)
        .arg(body)
        .query_async(&mut conn)
        .await
        .context("redis PUBLISH")?;
    Ok(())
}

fn which(prog: &str) -> bool {
    if let Ok(path) = std::env::var("PATH") {
        for dir in path.split(':') {
            let candidate = std::path::Path::new(dir).join(prog);
            if candidate.is_file() {
                return true;
            }
        }
    }
    false
}

// Convenience builder for callers that don't want to assemble Value by hand.
#[allow(dead_code)]
pub fn build_payload(level: &str, title: &str, message: &str, details: Option<Value>) -> Value {
    json!({
        "level": level,
        "title": title,
        "message": message,
        "timestamp": Utc::now().to_rfc3339(),
        "details": details.unwrap_or(Value::Null),
    })
}
