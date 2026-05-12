//! Memory pressure guardian — kill expendables on WARN, escalate to Claude Code on CRIT.
//!
//! Mirrors `agent_metrics.guardian`. Cooldown + age-protection + grace period preserved.

use crate::config::Settings;
use crate::proc_query::{find_claude_processes, find_processes, ClaudeProc};
use crate::store::{insert_guardian_actions, GuardianAction};
use anyhow::Result;
use once_cell::sync::Lazy;
use sqlx::SqlitePool;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::process::Command;

static GUARDIAN_STATE: Lazy<Mutex<GuardianState>> = Lazy::new(|| Mutex::new(GuardianState::default()));

#[derive(Debug, Default)]
struct GuardianState {
    last_run_epoch: f64,
    crit_streak: u32,
}

/// Settings used by guardian (Phase 2 inline; moves into `Settings` later).
#[derive(Debug, Clone)]
pub struct GuardianConfig {
    pub warn_threshold: i64,
    pub crit_threshold: i64,
    pub idle_cpu: f64,
    pub min_age: i64,
    pub grace_seconds: u64,
    pub cooldown: f64,
    pub sustained_checks: u32,
    /// (substring_pattern, display_name) — same as Python `expendable_list`.
    pub expendables: Vec<(String, String)>,
}

impl GuardianConfig {
    pub fn default_for(_settings: &Settings) -> Self {
        Self {
            warn_threshold: 40,
            crit_threshold: 8,
            idle_cpu: 1.0,
            min_age: 600,
            grace_seconds: 60,
            cooldown: 120.0,
            sustained_checks: 3,
            expendables: vec![
                ("Google Chrome Helper (Renderer)".into(), "Chrome Tabs".into()),
                ("LINE".into(), "LINE".into()),
                ("LineCall".into(), "LINE Call".into()),
                ("openclaw-gateway".into(), "OpenClaw".into()),
                ("AltServer".into(), "AltServer".into()),
            ],
        }
    }
}

pub async fn maybe_run_guardian(
    pool: &SqlitePool,
    cfg: &GuardianConfig,
    pressure: i64,
) -> Result<usize> {
    let now = now_epoch();
    {
        let state = GUARDIAN_STATE.lock().unwrap();
        if now - state.last_run_epoch < cfg.cooldown {
            return Ok(0);
        }
    }

    // Re-read pressure right now (Python does same to avoid stale data)
    let fresh_pressure = match read_pressure().await {
        Some(v) => v,
        None => {
            return Ok(0);
        }
    };
    if fresh_pressure >= cfg.warn_threshold {
        let mut state = GUARDIAN_STATE.lock().unwrap();
        state.crit_streak = 0;
        return Ok(0);
    }

    let _ = pressure; // unused, kept for parity with Python signature

    let (level, _crit_streak) = {
        let mut state = GUARDIAN_STATE.lock().unwrap();
        state.last_run_epoch = now;
        let is_crit_reading = fresh_pressure < cfg.crit_threshold;
        if is_crit_reading {
            state.crit_streak += 1;
        } else {
            state.crit_streak = 0;
        }
        let sustained = state.crit_streak >= cfg.sustained_checks;
        let level = if sustained { "CRIT" } else { "WARN" };
        (level.to_string(), state.crit_streak)
    };

    tracing::warn!(
        level = %level,
        pressure = fresh_pressure,
        "guardian_triggered"
    );

    let mut actions = Vec::new();
    actions.extend(kill_expendables(cfg, &level).await);
    if level == "CRIT" {
        actions.extend(kill_claude_code(cfg, &level).await);
    }

    if !actions.is_empty() {
        if let Err(e) = insert_guardian_actions(pool, &actions).await {
            tracing::error!(error = %e, "guardian_save_failed");
        }
    }

    tracing::info!(level = %level, count = actions.len(), "guardian_complete");
    Ok(actions.len())
}

async fn read_pressure() -> Option<i64> {
    let out = Command::new("sysctl")
        .args(["-n", "kern.memorystatus_level"])
        .output()
        .await
        .ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8_lossy(&out.stdout).trim().parse().ok()
}

/// Send `sig` to `pid` after probing existence — replaces the previous
/// hand-rolled `extern "C" kill()` FFI block with `nix::sys::signal::kill`.
/// Errors map to Python's `os.kill` semantics: ESRCH → "already_dead",
/// EPERM → "failed".
fn safe_kill(pid: i32, sig: nix::sys::signal::Signal) -> &'static str {
    use nix::errno::Errno;
    use nix::sys::signal::kill;
    use nix::unistd::Pid;
    let p = Pid::from_raw(pid);
    if let Err(e) = kill(p, None) {
        return match e {
            Errno::ESRCH => "already_dead",
            _ => "failed",
        };
    }
    match kill(p, sig) {
        Ok(()) => "success",
        Err(Errno::ESRCH) => "already_dead",
        Err(_) => "failed",
    }
}

const SIGTERM: nix::sys::signal::Signal = nix::sys::signal::Signal::SIGTERM;
const SIGKILL: nix::sys::signal::Signal = nix::sys::signal::Signal::SIGKILL;

async fn kill_expendables(cfg: &GuardianConfig, level: &str) -> Vec<GuardianAction> {
    let mut actions = Vec::new();
    for (pattern, display_name) in &cfg.expendables {
        let mut procs = find_processes(pattern).await;
        procs.sort_by(|a, b| b.rss_kb.cmp(&a.rss_kb));
        for p in procs {
            let result = safe_kill(p.pid, SIGTERM);
            let mem_mb = p.rss_kb as f64 / 1024.0;
            actions.push(GuardianAction::new(
                level,
                "P1",
                Some(p.pid),
                display_name.clone(),
                round1(mem_mb),
                p.cpu,
                "TERM",
                result,
                None,
            ));
            tracing::info!(
                priority = "P1",
                name = %display_name,
                pid = p.pid,
                mem_mb = mem_mb as i64,
                result = %result,
                "guardian_kill"
            );
        }
    }
    actions
}

async fn kill_claude_code(cfg: &GuardianConfig, level: &str) -> Vec<GuardianAction> {
    let mut actions = Vec::new();
    let now_epoch_i = now_epoch() as i64;
    for p in find_claude_processes().await {
        let age = now_epoch_i - p.start_epoch;
        if age < cfg.min_age {
            actions.push(GuardianAction::new(
                level,
                "P2",
                Some(p.pid),
                "Claude Code",
                round1(p.rss_kb as f64 / 1024.0),
                p.cpu,
                "SKIP",
                "skipped",
                Some(format!("too_young_{}s", age)),
            ));
            continue;
        }
        let mem_mb = p.rss_kb as f64 / 1024.0;
        if p.cpu < cfg.idle_cpu {
            let result = safe_kill(p.pid, SIGTERM);
            actions.push(GuardianAction::new(
                level,
                "P2",
                Some(p.pid),
                "Claude Code (idle)",
                round1(mem_mb),
                p.cpu,
                "TERM",
                result,
                None,
            ));
            tracing::info!(priority = "P2", pid = p.pid, result = %result, "guardian_kill");
        } else {
            let result = safe_kill(p.pid, SIGTERM);
            actions.push(GuardianAction::new(
                level,
                "P3",
                Some(p.pid),
                "Claude Code (active)",
                round1(mem_mb),
                p.cpu,
                "TERM",
                result,
                Some(format!("grace_{}s", cfg.grace_seconds)),
            ));
            tracing::warn!(priority = "P3", pid = p.pid, result = %result, "guardian_kill");
            if result == "success" {
                spawn_grace_kill(p.pid, cfg.grace_seconds);
            }
        }
        let _ = ClaudeProc {
            pid: p.pid,
            rss_kb: p.rss_kb,
            cpu: p.cpu,
            start_epoch: p.start_epoch,
        };
    }
    actions
}

fn spawn_grace_kill(pid: i32, grace_seconds: u64) {
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_secs(grace_seconds)).await;
        use nix::sys::signal::kill;
        use nix::unistd::Pid;
        let p = Pid::from_raw(pid);
        if kill(p, None).is_ok() {
            match kill(p, SIGKILL) {
                Ok(()) => tracing::warn!(pid, "guardian_force_kill"),
                Err(_) => tracing::warn!(pid, "guardian_force_kill_denied"),
            }
        }
    });
}

fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}
