use figment::{providers::{Env, Format, Yaml}, Figment};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub port: u16,
    pub host: String,
    pub database_path: PathBuf,
    pub redis_url: String,
    pub redis_push_channel: String,
    pub lock_dir: PathBuf,
    pub log_dir: PathBuf,
    pub check_light_interval_sec: u64,
    pub check_intervention_delay_sec: u64,
    pub check_repair_timeout_sec: u64,
    pub repair_monitor_interval_sec: u64,
    pub purge_interval_sec: u64,
    pub purge_retention_days: i64,
    pub notification_cooldown_sec: u64,
    pub sysmon_url: String,
}

impl Config {
    pub fn load(path: &str) -> anyhow::Result<Self> {
        let cfg: Config = Figment::new()
            .merge(Yaml::file(path))
            .merge(Env::prefixed("SENTINEL_"))
            .extract()?;
        Ok(cfg)
    }
}
