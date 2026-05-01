//! Runtime configuration. Mirrors Python `config.json` plus env overrides.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    pub data_dir: PathBuf,
    pub snapshot_interval_secs: u64,
    pub disk_broadcast_interval_secs: u64,
    pub dashboard_broadcast_interval_secs: u64,
    pub guardian_warn_threshold: u32,
    pub guardian_crit_threshold: u32,
    pub redis_url: Option<String>,
    pub litellm_url: Option<String>,
    pub litellm_token: Option<String>,
    pub gemini_api_key: Option<String>,
    pub hostname: String,
}

impl Settings {
    pub fn from_env() -> Self {
        let home = std::env::var("HOME").unwrap_or_else(|_| "/Users/joneshong".to_string());
        let data_dir = std::env::var("SYSTEM_MONITOR_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(format!("{home}/.claude/data/system-monitor")));

        Self {
            data_dir,
            snapshot_interval_secs: parse_env_u64("SYSMON_SNAPSHOT_INTERVAL_S", 300),
            disk_broadcast_interval_secs: parse_env_u64("SYSMON_DISK_BROADCAST_S", 300),
            dashboard_broadcast_interval_secs: parse_env_u64("SYSMON_DASHBOARD_BROADCAST_S", 30),
            guardian_warn_threshold: parse_env_u64("SYSMON_GUARDIAN_WARN", 40) as u32,
            guardian_crit_threshold: parse_env_u64("SYSMON_GUARDIAN_CRIT", 15) as u32,
            redis_url: std::env::var("REDIS_URL").ok(),
            litellm_url: std::env::var("LITELLM_URL").ok(),
            litellm_token: std::env::var("LITELLM_TOKEN").ok(),
            gemini_api_key: std::env::var("GEMINI_API_KEY").ok(),
            hostname: gethostname(),
        }
    }
}

fn parse_env_u64(key: &str, default: u64) -> u64 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn gethostname() -> String {
    std::process::Command::new("hostname")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown".to_string())
}
