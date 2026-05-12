//! Snapshot + alert persistence — JSON files in `~/.claude/data/system-monitor/`.

use anyhow::Result;
use serde_json::{json, Value};

use crate::config::Settings;

pub fn list_snapshots(cfg: &Settings, limit: usize) -> Result<Value> {
    let dir = crate::shared::paths::snapshots_dir(cfg);
    if !dir.exists() {
        return Ok(json!([]));
    }
    let mut entries: Vec<_> = std::fs::read_dir(&dir)?
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_name()
                .to_string_lossy()
                .starts_with("snapshot-")
        })
        .collect();
    entries.sort_by_key(|e| std::cmp::Reverse(e.file_name()));
    entries.truncate(limit);
    let mut out = Vec::new();
    for e in entries {
        if let Ok(s) = std::fs::read_to_string(e.path()) {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                out.push(v);
            }
        }
    }
    Ok(json!(out))
}

pub fn list_alerts(cfg: &Settings) -> Result<Value> {
    let dir = crate::shared::paths::alerts_dir(cfg);
    if !dir.exists() {
        return Ok(json!([]));
    }
    let mut entries: Vec<_> = std::fs::read_dir(&dir)?
        .filter_map(|e| e.ok())
        .collect();
    entries.sort_by_key(|e| std::cmp::Reverse(e.file_name()));
    let mut out = Vec::new();
    for e in entries {
        if let Ok(s) = std::fs::read_to_string(e.path()) {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                out.push(v);
            }
        }
    }
    Ok(json!(out))
}

pub fn save_snapshot(cfg: &Settings, snapshot: &Value) -> Result<()> {
    crate::shared::paths::ensure_dirs(cfg)?;
    let ts = chrono::Utc::now().format("%Y-%m-%dT%H-%M-%S").to_string();
    let path = crate::shared::paths::snapshot_path(cfg, &ts);
    std::fs::write(path, serde_json::to_string_pretty(snapshot)?)?;
    Ok(())
}
