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

    /// Directory where hook-dispatcher (Go binary) writes Claude Code hook
    /// events as JSONL. Replaces the old HTTP `hook_url` after the
    /// hook-observatory station was archived 2026-05-13. Override via
    /// `AGENT_METRICS_SPOOL_DIR` or `HOOK_OBS_SPOOL_DIR`.
    pub spool_dir: String,
    pub fallback_path: String,

    pub sysmon_collect_interval: u64,
    pub sysmon_history_size: usize,
    pub sysmon_output_path: String,

    pub static_dir: String,
    pub templates_dir: String,

    pub routing_table_path: String,
    pub skills_dir: String,
    pub default_timeout_s: u64,
}

impl Settings {
    pub fn from_env() -> Self {
        let cargo_dir = station_dir();
        let default_sqlite = cargo_dir.join("data").join("agent_metrics.sqlite");
        let default_static = cargo_dir.join("static");
        let default_templates = cargo_dir.join("templates");

        Self {
            service_name: env_or("SERVICE_NAME", "agent-metrics"),
            host: env_or("HOST", "127.0.0.1"),
            port: env_or(
                "PORT",
                &workshop_port_registry::get("agent-metrics")
                    .map(|s| s.port.to_string())
                    .unwrap_or_else(|| "10103".into()),
            )
            .parse()
            .unwrap_or(10103),
            debug: env_bool("DEBUG", false),

            sqlite_path: env_or("SQLITE_PATH", default_sqlite.to_string_lossy().as_ref()),
            redis_url: env_or("REDIS_URL", "redis://localhost:6379/0"),

            litellm_base_url: env_or("LITELLM_BASE_URL", &yaml_url("litellm", "", 4000)),
            litellm_master_key: env_or("LITELLM_MASTER_KEY", "sk-litellm-local-dev"),

            spool_dir: env_or(
                "SPOOL_DIR",
                crate::spool::default_spool_dir().to_string_lossy().as_ref(),
            ),
            fallback_path: env_or("FALLBACK_PATH", "/tmp/agent-metrics-latest.json"),

            sysmon_collect_interval: env_or("SYSMON_COLLECT_INTERVAL", "5")
                .parse()
                .unwrap_or(5),
            sysmon_history_size: env_or("SYSMON_HISTORY_SIZE", "720")
                .parse()
                .unwrap_or(720),
            sysmon_output_path: env_or("SYSMON_OUTPUT_PATH", "/tmp/agent-metrics-sysmon.json"),

            static_dir: env_or("STATIC_DIR", default_static.to_string_lossy().as_ref()),
            templates_dir: env_or(
                "TEMPLATES_DIR",
                default_templates.to_string_lossy().as_ref(),
            ),

            routing_table_path: env_or(
                "ROUTING_TABLE_PATH",
                cargo_dir
                    .join("config")
                    .join("routing_table.yaml")
                    .to_string_lossy()
                    .as_ref(),
            ),
            skills_dir: env_or(
                "SKILLS_DIR",
                std::env::var("HOME")
                    .map(|h| format!("{h}/.claude/skills"))
                    .unwrap_or_else(|_| "/Users/joneshong/.claude/skills".into())
                    .as_str(),
            ),
            default_timeout_s: env_or("DEFAULT_TIMEOUT", "300").parse().unwrap_or(300),
        }
    }
}

pub fn station_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// Build a service URL by looking up port from ports.yaml codegen,
/// falling back to the supplied port if the service is absent from the
/// registry (keeps service bootable when yaml has not been updated yet).
pub fn yaml_url(service: &str, path: &str, fallback_port: u16) -> String {
    let port = workshop_port_registry::get(service)
        .map(|s| s.port)
        .unwrap_or(fallback_port);
    format!("http://127.0.0.1:{port}{path}")
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

#[cfg(test)]
mod tests {
    use super::*;

    /// yaml_url must derive port from port_registry.yaml when the service exists.
    /// Regression guard for the drift-debt migration (P3, 2026-05-12).
    /// Asserted against agent-metrics itself — hook-observatory was the
    /// original target but that station was archived 2026-05-13.
    #[test]
    fn yaml_url_uses_registry_port_when_present() {
        let url = yaml_url("agent-metrics", "/health", 9999);
        let expected_port = workshop_port_registry::get("agent-metrics")
            .expect("agent-metrics must be in port_registry.yaml")
            .port;
        assert_eq!(url, format!("http://127.0.0.1:{expected_port}/health"));
    }

    /// yaml_url falls back to fallback_port if the service is not in yaml.
    #[test]
    fn yaml_url_falls_back_when_service_missing() {
        let url = yaml_url("nonexistent-service-xyz", "/api", 12345);
        assert_eq!(url, "http://127.0.0.1:12345/api");
    }
}

