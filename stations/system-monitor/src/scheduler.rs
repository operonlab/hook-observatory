//! launchd plist management — enable/disable/restart/logs (already used by
//! the HTTP API) plus higher-level `ensure_weekly_plist` / `ensure_monthly_plist`
//! that materialise the periodic-report plists this station owns.
//!
//! Mirrors `stations/system-monitor/scheduler.py`: weekly = Mon 05:00,
//! monthly = day 1 05:00, both invoking `system-monitor reporter --type=…`.

use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use crate::config::Settings;

const LABEL_PREFIX: &str = "com.workshop.system-monitor";
const LAUNCHCTL_TIMEOUT_SECS: u64 = 10;

// ─── Existing low-level helpers (kept as-is, used by api/mod.rs) ────────────────

pub async fn enable(label: &str) -> Result<Value> {
    let plist = format!("/Library/LaunchAgents/{label}.plist");
    let user_plist = std::env::var("HOME")
        .map(|h| format!("{h}/Library/LaunchAgents/{label}.plist"))
        .unwrap_or_default();
    let plist_path = if std::path::Path::new(&user_plist).exists() {
        user_plist
    } else {
        plist
    };
    let out = tokio::process::Command::new("launchctl")
        .args(["load", &plist_path])
        .output()
        .await?;
    Ok(json!({
        "ok": out.status.success(),
        "label": label,
        "stderr": String::from_utf8_lossy(&out.stderr),
    }))
}

pub async fn disable(label: &str) -> Result<Value> {
    let user_plist = std::env::var("HOME")
        .map(|h| format!("{h}/Library/LaunchAgents/{label}.plist"))
        .unwrap_or_default();
    let out = tokio::process::Command::new("launchctl")
        .args(["unload", &user_plist])
        .output()
        .await?;
    Ok(json!({
        "ok": out.status.success(),
        "label": label,
        "stderr": String::from_utf8_lossy(&out.stderr),
    }))
}

pub async fn restart(label: &str) -> Result<Value> {
    disable(label).await.ok();
    enable(label).await
}

pub async fn logs(label: &str, lines: usize) -> Result<Value> {
    let candidates = [
        format!("/tmp/{label}.log"),
        format!("/tmp/{label}.err"),
        format!("/var/log/{label}.log"),
    ];
    for c in &candidates {
        if std::path::Path::new(c).exists() {
            let out = tokio::process::Command::new("tail")
                .args(["-n", &lines.to_string(), c])
                .output()
                .await?;
            return Ok(json!({
                "label": label,
                "path": c,
                "lines": String::from_utf8_lossy(&out.stdout),
            }));
        }
    }
    Ok(json!({"label": label, "path": null, "lines": ""}))
}

// ─── High-level managed-plist API ───────────────────────────────────────────────

#[derive(Debug, Clone, Copy)]
pub enum ReportKind {
    Weekly,
    Monthly,
}

impl ReportKind {
    fn label(self) -> &'static str {
        match self {
            ReportKind::Weekly => "com.workshop.system-monitor-weekly",
            ReportKind::Monthly => "com.workshop.system-monitor-monthly",
        }
    }
    fn cli_arg(self) -> &'static str {
        match self {
            ReportKind::Weekly => "weekly",
            ReportKind::Monthly => "monthly",
        }
    }
    /// (key, value) pairs for `<StartCalendarInterval>`.
    fn calendar(self) -> Vec<(&'static str, i32)> {
        match self {
            // Monday 05:00
            ReportKind::Weekly => vec![("Weekday", 1), ("Hour", 5), ("Minute", 0)],
            // 1st of month 05:00
            ReportKind::Monthly => vec![("Day", 1), ("Hour", 5), ("Minute", 0)],
        }
    }
}

fn launch_agents_dir() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".into()))
        .join("Library/LaunchAgents")
}

fn plist_path_for(label: &str) -> PathBuf {
    launch_agents_dir().join(format!("{label}.plist"))
}

/// Enumerate plist files under `~/Library/LaunchAgents/` whose label matches
/// `com.workshop.system-monitor-*`. Returns one JSON entry per file.
pub fn list_managed_plists(_cfg: &Settings) -> Result<Vec<Value>> {
    let dir = launch_agents_dir();
    let mut out = Vec::new();
    let entries = match std::fs::read_dir(&dir) {
        Ok(e) => e,
        Err(_) => return Ok(out),
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        if !name.starts_with(&format!("{LABEL_PREFIX}-")) || !name.ends_with(".plist") {
            continue;
        }
        let label = name.trim_end_matches(".plist").to_string();
        out.push(json!({
            "label": label,
            "path": path.display().to_string(),
            "exists": true,
        }));
    }
    Ok(out)
}

/// Write & `launchctl load` the weekly report plist.
pub fn ensure_weekly_plist(cfg: &Settings) -> Result<()> {
    ensure_plist(cfg, ReportKind::Weekly)
}

/// Write & `launchctl load` the monthly report plist.
pub fn ensure_monthly_plist(cfg: &Settings) -> Result<()> {
    ensure_plist(cfg, ReportKind::Monthly)
}

fn ensure_plist(cfg: &Settings, kind: ReportKind) -> Result<()> {
    let label = kind.label();
    let plist_path = plist_path_for(label);
    std::fs::create_dir_all(launch_agents_dir())
        .with_context(|| format!("create {}", launch_agents_dir().display()))?;

    let logs_dir = cfg.data_dir.join("logs");
    std::fs::create_dir_all(&logs_dir)
        .with_context(|| format!("create logs dir {}", logs_dir.display()))?;

    let exe = current_exe_path();
    let body = render_plist_xml(label, &exe, kind, &logs_dir);
    std::fs::write(&plist_path, body)
        .with_context(|| format!("write plist {}", plist_path.display()))?;

    // Best-effort unload-then-load so an existing plist is replaced.
    let _ = std::process::Command::new("launchctl")
        .args(["unload", plist_path.to_string_lossy().as_ref()])
        .output();
    let out = std::process::Command::new("launchctl")
        .args(["load", plist_path.to_string_lossy().as_ref()])
        .output()
        .with_context(|| format!("launchctl load {}", plist_path.display()))?;
    if !out.status.success() {
        anyhow::bail!(
            "launchctl load failed: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
    let _ = LAUNCHCTL_TIMEOUT_SECS; // reserved for future timeout wiring
    Ok(())
}

fn current_exe_path() -> String {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
        .unwrap_or_else(|| "system-monitor".to_string())
}

fn render_plist_xml(label: &str, exe: &str, kind: ReportKind, logs_dir: &Path) -> String {
    let calendar_xml: String = kind
        .calendar()
        .into_iter()
        .map(|(k, v)| format!("        <key>{k}</key>\n        <integer>{v}</integer>\n"))
        .collect();
    let kind_arg = kind.cli_arg();
    let stdout = logs_dir.join(format!("{kind_arg}-stdout.log"));
    let stderr = logs_dir.join(format!("{kind_arg}-stderr.log"));
    let working = logs_dir.parent().unwrap_or(logs_dir);

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
        <string>reporter</string>
        <string>--type={kind_arg}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
{calendar_xml}    </dict>
    <key>WorkingDirectory</key>
    <string>{working}</string>
    <key>StandardOutPath</key>
    <string>{stdout}</string>
    <key>StandardErrorPath</key>
    <string>{stderr}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"#,
        label = label,
        exe = exe,
        kind_arg = kind_arg,
        calendar_xml = calendar_xml,
        working = working.display(),
        stdout = stdout.display(),
        stderr = stderr.display(),
    )
}
