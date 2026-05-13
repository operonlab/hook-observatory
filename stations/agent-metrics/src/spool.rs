//! Hook event spool reader.
//!
//! `~/.claude/hooks/hook-dispatcher` (Go binary) appends one JSON object per
//! line to `~/.hook-observatory/spool/events.jsonl`. Older daily archives
//! land beside it as `events-<timestamp>.processing` files (also JSONL).
//! agent-metrics consumes these locally — there is no HTTP API for hook
//! metrics since hook-observatory (FastAPI dashboard) was archived
//! 2026-05-13 (Phase A cutover).
//!
//! Design choices:
//!   * **Polling-style read** (no streaming, no offset state): callers
//!     re-scan the requested window each invocation. agent-metrics is
//!     CLI-triggered, not realtime, so this is sufficient.
//!   * **Graceful absence**: missing spool dir or empty files return an
//!     empty vector — never panic, never error to caller.
//!   * **Std-lib only**: serde_json + chrono + std::fs. No new deps.
//!
//! See `~/.claude/projects/-Users-joneshong-workshop/memory/`
//! `hook-dispatcher-go-source-of-truth.md` for the cutover rationale.

use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Default spool directory written by hook-dispatcher.
///
/// The dir name preserves the historical "hook-observatory" branding so
/// that the existing spool history stays continuous across the Python →
/// Go cutover; it is *not* an indication that the Python station is alive.
pub fn default_spool_dir() -> PathBuf {
    std::env::var("HOOK_OBS_SPOOL_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
            PathBuf::from(home).join(".hook-observatory").join("spool")
        })
}

/// One Claude Code hook event, as written by hook-dispatcher.
///
/// Schema is intentionally permissive — `data` is left untyped so new
/// fields added by the dispatcher don't break the reader.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HookEvent {
    /// Top-level event type (e.g. "PreToolUse", "PostToolUse", "Stop").
    pub event_type: String,
    /// ISO-8601 timestamp emitted by hook-dispatcher.
    #[serde(default)]
    pub ts: Option<DateTime<Utc>>,
    /// Raw payload — tool_name, session_id, hook_event_name, …
    #[serde(default)]
    pub data: serde_json::Value,
}

impl HookEvent {
    /// Convenience: pull `data.tool_name` if present.
    pub fn tool_name(&self) -> Option<&str> {
        self.data.get("tool_name").and_then(|v| v.as_str())
    }
}

/// Read all hook events from the spool dir whose `ts` falls within
/// `[since, until]` (inclusive). Pass `None` for unbounded ends.
///
/// Files considered: `events.jsonl` (live tail) + any `events-*.jsonl` or
/// `events-*.processing` archive. Unparseable lines are silently skipped
/// (logged at debug); missing dir returns Vec::new().
pub fn read_events(
    spool_dir: &Path,
    since: Option<DateTime<Utc>>,
    until: Option<DateTime<Utc>>,
) -> Vec<HookEvent> {
    let mut out = Vec::new();
    let entries = match std::fs::read_dir(spool_dir) {
        Ok(e) => e,
        Err(err) => {
            tracing::debug!(?err, spool_dir = %spool_dir.display(), "spool dir missing");
            return out;
        }
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if !is_spool_file(&path) {
            continue;
        }
        let contents = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(err) => {
                tracing::debug!(?err, path = %path.display(), "spool read failed");
                continue;
            }
        };
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let event: HookEvent = match serde_json::from_str(line) {
                Ok(e) => e,
                Err(_) => continue,
            };
            if let Some(ts) = event.ts {
                if let Some(s) = since {
                    if ts < s {
                        continue;
                    }
                }
                if let Some(u) = until {
                    if ts > u {
                        continue;
                    }
                }
            }
            out.push(event);
        }
    }
    out
}

fn is_spool_file(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
        return false;
    };
    if name == "events.jsonl" {
        return true;
    }
    if !name.starts_with("events-") {
        return false;
    }
    name.ends_with(".jsonl") || name.ends_with(".processing")
}

/// Group events by `event_type`, returning counts.
pub fn group_by_event_type(events: &[HookEvent]) -> std::collections::HashMap<String, usize> {
    let mut map = std::collections::HashMap::new();
    for e in events {
        *map.entry(e.event_type.clone()).or_insert(0) += 1;
    }
    map
}

/// Group PreToolUse events by `data.tool_name`, returning counts. Useful
/// for "which tool got called most this window" metrics.
pub fn group_by_tool(events: &[HookEvent]) -> std::collections::HashMap<String, usize> {
    let mut map = std::collections::HashMap::new();
    for e in events {
        if let Some(tool) = e.tool_name() {
            *map.entry(tool.to_string()).or_insert(0) += 1;
        }
    }
    map
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn tempdir(tag: &str) -> PathBuf {
        let base = std::env::temp_dir()
            .join(format!("agent-metrics-spool-test-{}-{}", tag, std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn missing_dir_returns_empty() {
        let path = PathBuf::from("/nonexistent/spool/dir/xyz");
        assert!(read_events(&path, None, None).is_empty());
    }

    #[test]
    fn reads_and_parses_events_jsonl() {
        let dir = tempdir("reads");
        let mut f = std::fs::File::create(dir.join("events.jsonl")).unwrap();
        writeln!(
            f,
            r#"{{"event_type":"PreToolUse","ts":"2026-05-13T11:42:07.000Z","data":{{"tool_name":"Bash"}}}}"#
        )
        .unwrap();
        writeln!(
            f,
            r#"{{"event_type":"PostToolUse","ts":"2026-05-13T11:43:00.000Z","data":{{"tool_name":"Bash"}}}}"#
        )
        .unwrap();
        writeln!(f, "").unwrap(); // blank line
        writeln!(f, "this is not json").unwrap(); // unparseable line — skipped
        drop(f);

        let events = read_events(&dir, None, None);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].event_type, "PreToolUse");
        assert_eq!(events[0].tool_name(), Some("Bash"));
    }

    #[test]
    fn time_window_filters_events() {
        let dir = tempdir("window");
        let mut f = std::fs::File::create(dir.join("events.jsonl")).unwrap();
        writeln!(
            f,
            r#"{{"event_type":"A","ts":"2026-05-13T10:00:00Z","data":{{}}}}"#
        )
        .unwrap();
        writeln!(
            f,
            r#"{{"event_type":"B","ts":"2026-05-13T11:00:00Z","data":{{}}}}"#
        )
        .unwrap();
        writeln!(
            f,
            r#"{{"event_type":"C","ts":"2026-05-13T12:00:00Z","data":{{}}}}"#
        )
        .unwrap();
        drop(f);

        let since: DateTime<Utc> = "2026-05-13T10:30:00Z".parse().unwrap();
        let until: DateTime<Utc> = "2026-05-13T11:30:00Z".parse().unwrap();
        let events = read_events(&dir, Some(since), Some(until));
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "B");
    }

    #[test]
    fn processing_archives_are_read() {
        let dir = tempdir("archive");
        let mut f = std::fs::File::create(dir.join("events-20260301T044418.processing")).unwrap();
        writeln!(
            f,
            r#"{{"event_type":"PreToolUse","ts":"2026-03-01T04:44:18Z","data":{{"tool_name":"Read"}}}}"#
        )
        .unwrap();
        drop(f);

        let events = read_events(&dir, None, None);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].tool_name(), Some("Read"));
    }

    #[test]
    fn group_helpers_aggregate_correctly() {
        let events = vec![
            HookEvent {
                event_type: "PreToolUse".into(),
                ts: None,
                data: serde_json::json!({"tool_name": "Bash"}),
            },
            HookEvent {
                event_type: "PreToolUse".into(),
                ts: None,
                data: serde_json::json!({"tool_name": "Bash"}),
            },
            HookEvent {
                event_type: "Stop".into(),
                ts: None,
                data: serde_json::json!({}),
            },
        ];
        let by_type = group_by_event_type(&events);
        assert_eq!(by_type.get("PreToolUse"), Some(&2));
        assert_eq!(by_type.get("Stop"), Some(&1));

        let by_tool = group_by_tool(&events);
        assert_eq!(by_tool.get("Bash"), Some(&2));
        assert_eq!(by_tool.get("Read"), None);
    }

    #[test]
    fn default_spool_dir_respects_env() {
        std::env::set_var("HOOK_OBS_SPOOL_DIR", "/tmp/custom-spool-xyz");
        let dir = default_spool_dir();
        assert_eq!(dir, PathBuf::from("/tmp/custom-spool-xyz"));
        std::env::remove_var("HOOK_OBS_SPOOL_DIR");
    }
}
