//! Settings — env-driven configuration mirroring Python `agent_metrics.config.Settings`.
//!
//! Env prefix: `AGENT_METRICS_*`
//!
//! Only Phase 1 fields are populated for now; later phases extend this struct.

use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Settings {
    pub service_name: String,
    pub host: String,
    pub port: u16,
    pub debug: bool,

    pub sqlite_path: String,
    pub redis_url: String,

    pub litellm_base_url: String,
    pub litellm_master_key: String,

    pub hook_url: String,
    pub fallback_path: String,

    pub sysmon_collect_interval: u64,
    pub sysmon_history_size: usize,
    pub sysmon_output_path: String,
}

impl Settings {
    pub fn from_env() -> Self {
        let station_dir = station_dir();
        let default_sqlite = station_dir.join("data").join("agent_metrics.sqlite");

        Self {
            service_name: env_or("SERVICE_NAME", "agent-metrics-rs"),
            host: env_or("HOST", "127.0.0.1"),
            port: env_or("PORT", "10103").parse().unwrap_or(10103),
            debug: env_bool("DEBUG", false),

            sqlite_path: env_or(
                "SQLITE_PATH",
                default_sqlite.to_string_lossy().as_ref(),
            ),
            redis_url: env_or("REDIS_URL", "redis://localhost:6379/0"),

            litellm_base_url: env_or("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
            litellm_master_key: env_or("LITELLM_MASTER_KEY", "sk-litellm-local-dev"),

            hook_url: env_or("HOOK_URL", "http://127.0.0.1:10100/api/hooks"),
            fallback_path: env_or("FALLBACK_PATH", "/tmp/agent-metrics-latest.json"),

            sysmon_collect_interval: env_or("SYSMON_COLLECT_INTERVAL", "5")
                .parse()
                .unwrap_or(5),
            sysmon_history_size: env_or("SYSMON_HISTORY_SIZE", "720")
                .parse()
                .unwrap_or(720),
            sysmon_output_path: env_or("SYSMON_OUTPUT_PATH", "/tmp/agent-metrics-sysmon.json"),
        }
    }
}

fn env_or(key: &str, default: &str) -> String {
    let full = format!("AGENT_METRICS_{key}");
    std::env::var(&full).unwrap_or_else(|_| default.to_string())
}

fn env_bool(key: &str, default: bool) -> bool {
    let full = format!("AGENT_METRICS_{key}");
    match std::env::var(&full) {
        Ok(v) => matches!(v.to_lowercase().as_str(), "1" | "true" | "yes" | "on"),
        Err(_) => default,
    }
}

fn station_dir() -> PathBuf {
    // Resolved as the CARGO_MANIFEST_DIR at compile time, which points to
    // `stations/agent-metrics-rs`. At runtime we fall back to CWD.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
