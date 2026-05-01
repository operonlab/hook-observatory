//! Filesystem layout for `~/.claude/data/system-monitor/`.
//! Must stay byte-identical to the Python version so old snapshots / logs
//! remain readable through the swap.

use crate::config::Settings;
use std::path::PathBuf;

pub fn snapshots_dir(cfg: &Settings) -> PathBuf {
    cfg.data_dir.clone()
}

pub fn snapshot_path(cfg: &Settings, iso_ts: &str) -> PathBuf {
    cfg.data_dir.join(format!("snapshot-{iso_ts}.json"))
}

pub fn logs_dir(cfg: &Settings) -> PathBuf {
    cfg.data_dir.join("logs")
}

pub fn guardian_log_path(cfg: &Settings) -> PathBuf {
    logs_dir(cfg).join("guardian.log")
}

pub fn guardian_status_path(cfg: &Settings) -> PathBuf {
    logs_dir(cfg).join("guardian-status.json")
}

pub fn alerts_dir(cfg: &Settings) -> PathBuf {
    cfg.data_dir.join("alerts")
}

pub fn alert_path(cfg: &Settings, iso_ts: &str) -> PathBuf {
    alerts_dir(cfg).join(format!("alert-{iso_ts}.json"))
}

pub fn reports_dir(cfg: &Settings) -> PathBuf {
    cfg.data_dir.join("reports")
}

pub fn report_path(cfg: &Settings, kind: &str, date: &str) -> PathBuf {
    reports_dir(cfg).join(format!("{kind}-{date}.md"))
}

pub fn ensure_dirs(cfg: &Settings) -> std::io::Result<()> {
    std::fs::create_dir_all(&cfg.data_dir)?;
    std::fs::create_dir_all(logs_dir(cfg))?;
    std::fs::create_dir_all(alerts_dir(cfg))?;
    std::fs::create_dir_all(reports_dir(cfg))?;
    Ok(())
}
