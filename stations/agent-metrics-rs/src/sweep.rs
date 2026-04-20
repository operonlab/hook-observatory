//! Process sweep — kill MCP orphans, zombies' parents, CPU hogs, stale Node.
//!
//! Mirrors `agent_metrics.sweep`. Each sweep is best-effort: failures of one
//! sub-pass do not block the others.

use crate::config::Settings;
use crate::proc_query::{find_processes, ppid_of, process_details, run_ps};
use crate::store::{insert_guardian_actions, GuardianAction};
use anyhow::Result;
use once_cell::sync::Lazy;
use serde::Deserialize;
use sqlx::SqlitePool;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

const SIGTERM: i32 = 15;
const SIGCHLD: i32 = 20;

const MCP_CACHE_TTL: f64 = 300.0;

static SWEEP_STATE: Lazy<Mutex<SweepState>> = Lazy::new(|| Mutex::new(SweepState::default()));
static MCP_PATTERN_CACHE: Lazy<Mutex<(f64, Vec<String>)>> = Lazy::new(|| Mutex::new((0.0, vec![])));

#[derive(Debug, Default)]
struct SweepState {
    last_sweep_epoch: f64,
}

#[derive(Debug, Clone)]
pub struct SweepConfig {
    pub interval: f64,
    pub cpu_threshold: f64,
    pub cpu_min_age: i64,
    pub cpu_whitelist: Vec<String>,
    pub stale_warn_hours: i64,
    pub stale_kill_hours: i64,
    pub stale_whitelist: Vec<String>,
    pub mcp_config_paths: Vec<String>,
    pub mcp_extra_patterns: Vec<String>,
}

impl SweepConfig {
    pub fn default_for(_settings: &Settings) -> Self {
        Self {
            interval: 1800.0,
            cpu_threshold: 80.0,
            cpu_min_age: 600,
            cpu_whitelist: vec!["claude".into(), "ollama".into()],
            stale_warn_hours: 24,
            stale_kill_hours: 48,
            stale_whitelist: vec!["claude".into(), "cost-server".into(), "browser-tools-server".into()],
            mcp_config_paths: vec!["~/.mcp.json".into(), "~/workshop/.mcp.json".into()],
            mcp_extra_patterns: vec![],
        }
    }
}

pub async fn maybe_run_sweep(pool: &SqlitePool, cfg: &SweepConfig) -> Result<usize> {
    let now = now_epoch();
    {
        let state = SWEEP_STATE.lock().unwrap();
        if now - state.last_sweep_epoch < cfg.interval {
            return Ok(0);
        }
    }
    {
        let mut state = SWEEP_STATE.lock().unwrap();
        state.last_sweep_epoch = now;
    }
    tracing::info!("sweep_started");

    let mut actions = Vec::new();
    actions.extend(sweep_mcp_orphans(cfg).await);
    actions.extend(sweep_zombies().await);
    actions.extend(sweep_cpu_hogs(cfg).await);
    actions.extend(sweep_stale_node(cfg).await);

    if !actions.is_empty() {
        if let Err(e) = insert_guardian_actions(pool, &actions).await {
            tracing::error!(error = %e, "sweep_save_failed");
        }
    }
    tracing::info!(cleaned = actions.len(), "sweep_complete");
    Ok(actions.len())
}

#[derive(Deserialize)]
struct McpConfigFile {
    #[serde(rename = "mcpServers", default)]
    mcp_servers: serde_json::Value,
}

fn load_mcp_patterns(cfg: &SweepConfig) -> Vec<String> {
    let now = now_epoch();
    {
        let cache = MCP_PATTERN_CACHE.lock().unwrap();
        if !cache.1.is_empty() && now - cache.0 < MCP_CACHE_TTL {
            return cache.1.clone();
        }
    }
    let mut patterns: BTreeSet<String> = BTreeSet::new();
    for path in &cfg.mcp_config_paths {
        let expanded = expand_home(path);
        if let Ok(text) = std::fs::read_to_string(&expanded) {
            if let Ok(parsed) = serde_json::from_str::<McpConfigFile>(&text) {
                if let Some(obj) = parsed.mcp_servers.as_object() {
                    for k in obj.keys() {
                        patterns.insert(k.clone());
                    }
                }
            }
        }
    }
    for p in &cfg.mcp_extra_patterns {
        patterns.insert(p.clone());
    }
    let result: Vec<String> = patterns.into_iter().collect();
    {
        let mut cache = MCP_PATTERN_CACHE.lock().unwrap();
        *cache = (now, result.clone());
    }
    result
}

fn expand_home(p: &str) -> PathBuf {
    if let Some(stripped) = p.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return PathBuf::from(home).join(stripped);
        }
    }
    PathBuf::from(p)
}

async fn sweep_mcp_orphans(cfg: &SweepConfig) -> Vec<GuardianAction> {
    let mut actions = Vec::new();
    let has_active_claude = !find_processes("claude").await.is_empty();
    let mcp_patterns = load_mcp_patterns(cfg);

    for pattern in mcp_patterns {
        let candidates = find_processes(&pattern).await;
        for p in candidates {
            if has_active_claude {
                let pp = ppid_of(p.pid).await;
                if pp != 1 {
                    continue;
                }
            }
            let result = safe_signal(p.pid, SIGTERM);
            actions.push(GuardianAction::new(
                "SWEEP",
                "SWEEP-MCP",
                Some(p.pid),
                format!("mcp-orphan ({})", pattern),
                round1(p.rss_kb as f64 / 1024.0),
                p.cpu,
                "TERM",
                result,
                Some(if has_active_claude {
                    "ppid=1".into()
                } else {
                    "no_claude_parent".into()
                }),
            ));
            tracing::info!(pid = p.pid, pattern = %pattern, result = %result, "sweep_mcp_orphan");
        }
    }
    actions
}

async fn sweep_zombies() -> Vec<GuardianAction> {
    let mut actions = Vec::new();
    let raw = match run_ps(&["-eo", "pid=,ppid=,stat="]).await {
        Ok(s) => s,
        Err(_) => return actions,
    };
    let mut parents: BTreeSet<i32> = BTreeSet::new();
    let mut zombie_count = 0;
    for line in raw.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() >= 3 && parts[2].starts_with('Z') {
            zombie_count += 1;
            if let Ok(ppid) = parts[1].parse::<i32>() {
                parents.insert(ppid);
            }
        }
    }
    for ppid in parents {
        let result = safe_signal(ppid, SIGCHLD);
        actions.push(GuardianAction::new(
            "SWEEP",
            "SWEEP-ZOMBIE",
            Some(ppid),
            format!("zombie-parent ({} zombies)", zombie_count),
            0.0,
            0.0,
            "SIGCHLD",
            result,
            None,
        ));
        tracing::info!(ppid, zombie_count, result = %result, "sweep_zombie_parent");
    }
    actions
}

async fn sweep_cpu_hogs(cfg: &SweepConfig) -> Vec<GuardianAction> {
    let mut actions = Vec::new();
    let procs = match process_details().await {
        Ok(v) => v,
        Err(_) => return actions,
    };
    for p in procs {
        if p.ppid != 1 {
            continue;
        }
        if p.pid < 100 {
            continue;
        }
        if p.cpu < cfg.cpu_threshold {
            continue;
        }
        if p.etime_sec < cfg.cpu_min_age {
            continue;
        }
        if cfg.cpu_whitelist.iter().any(|w| p.command.contains(w)) {
            continue;
        }
        let age_min = p.etime_sec / 60;
        let result = safe_signal(p.pid, SIGTERM);
        actions.push(GuardianAction::new(
            "SWEEP",
            "SWEEP-CPU",
            Some(p.pid),
            truncate(&p.command, 80),
            round1(p.rss_kb as f64 / 1024.0),
            p.cpu,
            "TERM",
            result,
            Some(format!("cpu={}%,age={}m", p.cpu, age_min)),
        ));
        tracing::info!(pid = p.pid, cpu = p.cpu, age_min, result = %result, "sweep_cpu_hog");
    }
    actions
}

async fn sweep_stale_node(cfg: &SweepConfig) -> Vec<GuardianAction> {
    let mut actions = Vec::new();
    let procs = match process_details().await {
        Ok(v) => v,
        Err(_) => return actions,
    };
    let warn_sec = cfg.stale_warn_hours * 3600;
    let kill_sec = cfg.stale_kill_hours * 3600;

    for p in procs {
        if p.ppid != 1 {
            continue;
        }
        if !is_node_command(&p.command) {
            continue;
        }
        if cfg.stale_whitelist.iter().any(|w| p.command.contains(w)) {
            continue;
        }
        let age_hours = p.etime_sec as f64 / 3600.0;
        if p.etime_sec > kill_sec {
            let result = safe_signal(p.pid, SIGTERM);
            actions.push(GuardianAction::new(
                "SWEEP",
                "SWEEP-STALE-NODE",
                Some(p.pid),
                truncate(&p.command, 80),
                round1(p.rss_kb as f64 / 1024.0),
                p.cpu,
                "TERM",
                result,
                Some(format!(
                    "stale_kill_{}h,age={:.1}h",
                    cfg.stale_kill_hours, age_hours
                )),
            ));
            tracing::info!(pid = p.pid, age_hours = round1(age_hours), "sweep_stale_node_kill");
        } else if p.etime_sec > warn_sec {
            actions.push(GuardianAction::new(
                "SWEEP",
                "SWEEP-STALE-NODE",
                Some(p.pid),
                truncate(&p.command, 80),
                round1(p.rss_kb as f64 / 1024.0),
                p.cpu,
                "SKIP",
                "warn",
                Some(format!(
                    "stale_warn_{}h,age={:.1}h",
                    cfg.stale_warn_hours, age_hours
                )),
            ));
            tracing::warn!(pid = p.pid, age_hours = round1(age_hours), "sweep_stale_node_warn");
        }
    }
    actions
}

fn is_node_command(cmd: &str) -> bool {
    // Python regex: r"(?:^|/)node\s"
    // Match the literal `node` token that is either at start-of-string
    // or immediately preceded by `/`, AND immediately followed by whitespace.
    let bytes = cmd.as_bytes();
    if bytes.len() < 5 {
        return false;
    }
    let needle = b"node";
    let last = bytes.len() - 5;
    for i in 0..=last {
        if &bytes[i..i + 4] == needle {
            let prev_ok = i == 0 || bytes[i - 1] == b'/';
            let next = bytes[i + 4];
            let next_ok = next == b' ' || next == b'\t' || next == b'\n' || next == b'\r';
            if prev_ok && next_ok {
                return true;
            }
        }
    }
    false
}

fn safe_signal(pid: i32, sig: i32) -> &'static str {
    let probe = unsafe { libc_kill(pid, 0) };
    if probe != 0 {
        let errno = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
        if errno == 3 {
            return "already_dead";
        }
        if errno == 1 {
            return "no_permission";
        }
        return "no_permission";
    }
    let r = unsafe { libc_kill(pid, sig) };
    if r != 0 {
        let errno = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
        if errno == 3 {
            return "already_dead";
        }
        if errno == 1 {
            return "no_permission";
        }
        return "no_permission";
    }
    "success"
}

extern "C" {
    fn kill(pid: libc_pid_t, sig: libc_c_int) -> libc_c_int;
}

#[allow(non_camel_case_types)]
type libc_pid_t = i32;
#[allow(non_camel_case_types)]
type libc_c_int = i32;

unsafe fn libc_kill(pid: i32, sig: i32) -> i32 {
    kill(pid as libc_pid_t, sig as libc_c_int)
}

fn truncate(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
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

#[cfg(test)]
mod tests {
    use super::is_node_command;

    #[test]
    fn matches_basic_node() {
        assert!(is_node_command("/usr/local/bin/node script.js"));
        assert!(is_node_command("node main.js"));
        assert!(!is_node_command("not-node thing"));
        assert!(!is_node_command("node"));
        assert!(!is_node_command("nodejs script.js"));
        assert!(is_node_command("/opt/homebrew/bin/node\targ"));
    }
}
