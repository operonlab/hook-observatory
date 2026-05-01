//! Memory guardian. Phase 3 implementation — replaces
//! `stations/system-monitor/memory_guardian.py`.
//!
//! Pipeline (called once per `system-monitor-rs guardian-tick`):
//!   1. Snapshot: kern.memorystatus_level, vm_stat compressed, swap, idle
//!      seconds, top processes (ps), browser kind/total.
//!   2. Classify presence (Present / BriefAway / Away / Unknown).
//!   3. `thresholds::decide(snap, presence, &Thresholds)` → Vec<Action>.
//!   4. `actions::Executor::run()` — JSONL log, side-effects gated by
//!      `dry_run` (CLI flag OR env `SYSMON_GUARDIAN_FORCE_DRY=1`).
//!   5. Cooldown.flush() + heartbeat write.
//!
//! Heartbeat (`guardian-status.json`) schema:
//!   {
//!     "last_tick": "<rfc3339>",
//!     "mem_level": <u32>,
//!     "presence": "<Present|BriefAway|Away|Unknown>",
//!     "decided_actions": <count>,
//!     "executed_actions": <count>,
//!     "dry_run": <bool>,
//!     "snapshot": { "compressed_gb": …, "swap_used_pct": …, … },
//!   }

pub mod actions;
pub mod cooldown;
pub mod footprint;
pub mod presence;
pub mod thresholds;

use anyhow::Result;
use serde_json::{json, Value};
use std::process::Command;

use crate::config::Settings;
use crate::shared::paths::{ensure_dirs, guardian_log_path, guardian_status_path, logs_dir};

use self::actions::Executor;
use self::cooldown::Cooldown;
use self::presence::{classify_presence, read_user_idle_seconds};
use self::thresholds::{decide, Action, BrowserKind, NotifyLevel, ProcRow, Snapshot, Thresholds};

const DRY_RUN_ENV_VAR: &str = "SYSMON_GUARDIAN_FORCE_DRY";

/// Single guardian tick. Called from `main.rs guardian-tick` and (eventually)
/// from the in-process scheduler.
pub async fn tick(cfg: &Settings, dry_run_flag: bool) -> Result<()> {
    ensure_dirs(cfg)?;

    // env override: `SYSMON_GUARDIAN_FORCE_DRY=1` forces dry-run regardless
    // of the CLI flag. Used in staging to verify the rule engine without
    // actually killing anything.
    let env_force_dry = std::env::var(DRY_RUN_ENV_VAR)
        .map(|v| matches!(v.as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false);
    let dry_run = dry_run_flag || env_force_dry;

    let snapshot = build_snapshot();
    let presence = classify_presence(snapshot.idle_seconds);
    let th = Thresholds {
        warn: cfg.guardian_warn_threshold,
        crit: cfg.guardian_crit_threshold,
        ..Thresholds::default()
    };

    let plan = decide(&snapshot, presence, &th);

    // Notification cooldown — collapse repeated Notify actions into one
    // emission per cooldown bucket (the `group` field).
    let mut cd = Cooldown::load(logs_dir(cfg).join("guardian-cooldown.json"));
    let plan: Vec<Action> = plan
        .into_iter()
        .filter(|a| match a {
            Action::Notify { group, level, .. } => {
                let interval: u64 = match level {
                    NotifyLevel::Crit => 5 * 60,
                    NotifyLevel::Warn => 15 * 60,
                    NotifyLevel::Info => 30 * 60,
                };
                cd.should_fire(group, interval)
            }
            _ => true,
        })
        .collect();
    let _ = cd.flush();

    let log_path = guardian_log_path(cfg);
    let executor = Executor::new(&log_path, dry_run);
    let entries = executor.run(&plan)?;

    // Heartbeat
    let executed = entries
        .iter()
        .filter(|e| e["result"] != json!("dry_run") && e["result"] != json!("skipped"))
        .count();
    let payload = json!({
        "last_tick": chrono::Utc::now().to_rfc3339(),
        "mem_level": snapshot.mem_level,
        "presence": format!("{:?}", presence),
        "decided_actions": plan.len(),
        "executed_actions": executed,
        "dry_run": dry_run,
        "snapshot": {
            "mem_level": snapshot.mem_level,
            "compressed_gb": snapshot.compressed_gb,
            "swap_used_pct": snapshot.swap_used_pct,
            "swap_used_gb": snapshot.swap_used_gb,
            "idle_seconds": snapshot.idle_seconds,
            "browser_kind": format!("{:?}", snapshot.browser_kind),
            "browser_total_gb": snapshot.browser_total_gb,
        },
    });
    std::fs::write(
        guardian_status_path(cfg),
        serde_json::to_string_pretty(&payload)?,
    )?;
    Ok(())
}

/// Read the latest heartbeat + last 50 log lines. Used by `api/` routes.
pub fn get_state(cfg: &Settings) -> Result<Value> {
    let status_path = guardian_status_path(cfg);
    let status = if status_path.exists() {
        let raw = std::fs::read_to_string(&status_path)?;
        serde_json::from_str::<Value>(&raw).unwrap_or_else(|_| json!({}))
    } else {
        json!({})
    };

    let log_path = guardian_log_path(cfg);
    let entries: Vec<Value> = if log_path.exists() {
        let raw = std::fs::read_to_string(&log_path).unwrap_or_default();
        let mut lines: Vec<Value> = raw
            .lines()
            .rev()
            .take(50)
            .filter_map(|l| serde_json::from_str(l).ok())
            .collect();
        lines.reverse();
        lines
    } else {
        Vec::new()
    };

    Ok(json!({
        "status": status,
        "entries": entries,
    }))
}

// ── snapshot helpers (shell out — kept private to mod.rs) ────────────────

fn build_snapshot() -> Snapshot {
    let mem_level = read_mem_level().unwrap_or(100);
    let (compressed_gb, _stored_gb) = read_compressed_gb();
    let (swap_used_pct, swap_used_gb) = read_swap_usage();
    let idle_seconds = read_user_idle_seconds();
    let top_processes = read_top_processes(50);
    let (browser_kind, browser_total_gb) = derive_browser_state(&top_processes);

    Snapshot {
        mem_level,
        compressed_gb,
        swap_used_gb,
        swap_used_pct,
        idle_seconds,
        top_processes,
        browser_total_gb,
        browser_kind,
    }
}

fn read_mem_level() -> Option<u32> {
    let out = Command::new("/usr/sbin/sysctl")
        .args(["-n", "kern.memorystatus_level"])
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    s.parse().ok()
}

fn read_compressed_gb() -> (f64, f64) {
    // Reuse the same logic the collector uses, but inline here so the
    // guardian does not depend on collector internals (enables Phase 3
    // unit testing without spinning up sysinfo).
    let out = Command::new("vm_stat").output();
    let stdout = match out {
        Ok(o) => String::from_utf8_lossy(&o.stdout).to_string(),
        Err(_) => return (0.0, 0.0),
    };
    let page_size = Command::new("sysctl")
        .args(["-n", "hw.pagesize"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.trim().parse::<u64>().ok())
        .unwrap_or(16384);

    let parse_pages = |needle: &str| -> u64 {
        for line in stdout.lines() {
            if line.contains(needle) {
                if let Some(rest) = line.split(':').nth(1) {
                    return rest
                        .trim()
                        .trim_end_matches('.')
                        .parse::<u64>()
                        .unwrap_or(0);
                }
            }
        }
        0
    };

    let occupied = parse_pages("occupied by compressor");
    let stored = parse_pages("stored in compressor");
    let to_gb = |p: u64| (p * page_size) as f64 / (1024.0 * 1024.0 * 1024.0);
    (to_gb(occupied), to_gb(stored))
}

fn read_swap_usage() -> (u32, f64) {
    let out = Command::new("/usr/sbin/sysctl")
        .args(["-n", "vm.swapusage"])
        .output();
    let raw = match out {
        Ok(o) => String::from_utf8_lossy(&o.stdout).to_string(),
        Err(_) => return (0, 0.0),
    };
    // "total = 6144.00M  used = 1234.50M  free = ..."
    let parse_mb = |key: &str| -> Option<f64> {
        let idx = raw.find(key)?;
        let tail = &raw[idx + key.len()..];
        let token = tail.split_whitespace().next()?;
        token.trim_end_matches('M').parse::<f64>().ok()
    };
    let total_mb = parse_mb("total =").unwrap_or(0.0);
    let used_mb = parse_mb("used =").unwrap_or(0.0);
    let pct = if total_mb > 0.0 {
        (used_mb / total_mb * 100.0) as u32
    } else {
        0
    };
    (pct, used_mb / 1024.0)
}

fn read_top_processes(limit: usize) -> Vec<ProcRow> {
    // Format columns: pid rss(KB) %cpu etime command
    let out = Command::new("ps")
        .args(["-eo", "pid=,rss=,%cpu=,etime=,comm=,command="])
        .output();
    let stdout = match out {
        Ok(o) => String::from_utf8_lossy(&o.stdout).to_string(),
        Err(_) => return Vec::new(),
    };

    let mut rows: Vec<ProcRow> = Vec::new();
    for line in stdout.lines() {
        // We split into 6 columns by whitespace, but command may contain
        // spaces, so capture the rest manually.
        let mut parts = line.trim().splitn(6, char::is_whitespace);
        let pid: i32 = match parts.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let rss_kb: u64 = match parts.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let cpu_pct: f32 = match parts.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let etime = match parts.next() {
            Some(v) => v,
            None => continue,
        };
        let comm = match parts.next() {
            Some(v) => v.trim().to_string(),
            None => continue,
        };
        let command = match parts.next() {
            Some(v) => v.trim().to_string(),
            None => comm.clone(),
        };
        let age_secs = parse_etime(etime);
        rows.push(ProcRow {
            pid,
            name: shorten_name(&comm),
            command,
            rss_mb: rss_kb / 1024,
            cpu_pct,
            age_secs,
        });
    }

    rows.sort_by(|a, b| b.rss_mb.cmp(&a.rss_mb));
    rows.truncate(limit);
    rows
}

fn shorten_name(comm: &str) -> String {
    comm.rsplit('/').next().unwrap_or(comm).to_string()
}

fn parse_etime(s: &str) -> u64 {
    // ps etime: "[[dd-]hh:]mm:ss"
    let (days, rest) = match s.split_once('-') {
        Some((d, r)) => (d.parse::<u64>().unwrap_or(0), r),
        None => (0, s),
    };
    let parts: Vec<&str> = rest.split(':').collect();
    let (h, m, sec) = match parts.as_slice() {
        [h, m, s] => (
            h.parse::<u64>().unwrap_or(0),
            m.parse::<u64>().unwrap_or(0),
            s.parse::<u64>().unwrap_or(0),
        ),
        [m, s] => (
            0,
            m.parse::<u64>().unwrap_or(0),
            s.parse::<u64>().unwrap_or(0),
        ),
        _ => (0, 0, 0),
    };
    days * 86_400 + h * 3_600 + m * 60 + sec
}

fn derive_browser_state(procs: &[ProcRow]) -> (BrowserKind, f64) {
    let mut chrome_mb: u64 = 0;
    let mut safari_mb: u64 = 0;
    let mut firefox_mb: u64 = 0;
    for p in procs {
        let needle = &p.command;
        if needle.contains("Google Chrome Helper") {
            chrome_mb += p.rss_mb;
        } else if needle.contains("com.apple.WebKit.WebContent") {
            safari_mb += p.rss_mb;
        } else if needle.contains("plugin-container") {
            firefox_mb += p.rss_mb;
        }
    }
    let to_gb = |mb: u64| mb as f64 / 1024.0;
    if chrome_mb > 0 {
        (BrowserKind::Chrome, to_gb(chrome_mb))
    } else if safari_mb > 0 {
        (BrowserKind::Safari, to_gb(safari_mb))
    } else if firefox_mb > 0 {
        (BrowserKind::Firefox, to_gb(firefox_mb))
    } else {
        (BrowserKind::None, 0.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn etime_parses_compound() {
        assert_eq!(parse_etime("00:30"), 30);
        assert_eq!(parse_etime("5:00"), 300);
        assert_eq!(parse_etime("1:00:00"), 3_600);
        assert_eq!(parse_etime("2-03:04:05"), 2 * 86_400 + 3 * 3_600 + 4 * 60 + 5);
    }

    #[test]
    fn shorten_keeps_basename() {
        assert_eq!(shorten_name("/Applications/Google Chrome"), "Google Chrome");
        assert_eq!(shorten_name("claude"), "claude");
    }

    #[test]
    fn derive_browser_state_picks_chrome_first() {
        let procs = vec![
            ProcRow {
                pid: 1,
                name: "Helper".into(),
                command: "Google Chrome Helper (Renderer)".into(),
                rss_mb: 1024,
                cpu_pct: 1.0,
                age_secs: 100,
            },
            ProcRow {
                pid: 2,
                name: "WebKit".into(),
                command: "com.apple.WebKit.WebContent".into(),
                rss_mb: 500,
                cpu_pct: 0.5,
                age_secs: 100,
            },
        ];
        let (kind, gb) = derive_browser_state(&procs);
        assert_eq!(kind, BrowserKind::Chrome);
        assert!((gb - 1.0).abs() < 1e-6);
    }
}
