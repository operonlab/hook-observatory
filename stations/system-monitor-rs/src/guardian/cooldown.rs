//! Notification throttle. Mirrors `_check_cooldown()` in
//! `memory_guardian.py` but consolidated into a single JSON file rather
//! than scattered `.{group}_notify_cooldown` siblings.
//!
//! Schema (one JSON object, key = cooldown bucket name, value = epoch secs of
//! last fire):
//!     {"swap-crit": 1714557123.456, "compressed-warn": 1714557000.0}
//!
//! Persisted at `<data_dir>/logs/guardian-cooldown.json`. Failures fall back
//! to in-memory map silently — degraded notification accuracy is preferred
//! over a guardian that crashes when the disk is full.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use serde_json::{json, Value};

#[derive(Debug)]
pub struct Cooldown {
    path: PathBuf,
    state: HashMap<String, f64>,
}

impl Cooldown {
    /// Load the cooldown table from disk. Missing file → empty table.
    pub fn load(path: impl AsRef<Path>) -> Self {
        let path = path.as_ref().to_path_buf();
        let state = if path.exists() {
            std::fs::read_to_string(&path)
                .ok()
                .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
                .and_then(|v| v.as_object().cloned())
                .map(|map| {
                    map.into_iter()
                        .filter_map(|(k, v)| v.as_f64().map(|f| (k, f)))
                        .collect()
                })
                .unwrap_or_default()
        } else {
            HashMap::new()
        };
        Self { path, state }
    }

    /// Returns true and updates state if cooldown for `key` has expired.
    /// Caller is expected to call `flush()` once at the end of a tick.
    pub fn should_fire(&mut self, key: &str, min_interval_secs: u64) -> bool {
        let now = unix_secs();
        let last = self.state.get(key).copied().unwrap_or(0.0);
        if now - last >= min_interval_secs as f64 {
            self.state.insert(key.to_string(), now);
            true
        } else {
            false
        }
    }

    /// Persist the in-memory table back to disk. Best-effort: errors are
    /// swallowed so a write failure doesn't crash the guardian tick.
    pub fn flush(&self) -> Result<()> {
        if let Some(parent) = self.path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let payload = json!(self.state);
        std::fs::write(&self.path, serde_json::to_string_pretty(&payload)?)?;
        Ok(())
    }
}

fn unix_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    fn temp_path(name: &str) -> PathBuf {
        let mut p = env::temp_dir();
        p.push(format!("guardian-cooldown-{}-{}.json", name, std::process::id()));
        p
    }

    #[test]
    fn first_call_fires() {
        let mut cd = Cooldown::load(temp_path("first"));
        assert!(cd.should_fire("group-a", 60));
    }

    #[test]
    fn second_call_within_interval_blocked() {
        let mut cd = Cooldown::load(temp_path("second"));
        assert!(cd.should_fire("group-b", 600));
        assert!(!cd.should_fire("group-b", 600));
    }

    #[test]
    fn flush_and_reload_round_trip() {
        let path = temp_path("roundtrip");
        let _ = std::fs::remove_file(&path);
        let mut cd = Cooldown::load(&path);
        cd.should_fire("group-c", 3600);
        cd.flush().expect("flush ok");
        let mut cd2 = Cooldown::load(&path);
        // Loaded state means second instance sees cooldown still active.
        assert!(!cd2.should_fire("group-c", 3600));
        let _ = std::fs::remove_file(&path);
    }
}
