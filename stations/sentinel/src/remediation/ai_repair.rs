//! Layer 3 AI repair via tmux-relay (1:1 port of remediation.py Remediator).
//!
//! Flow:
//!   1. `python3 pane_pool.py acquire 1` → pane id
//!   2. Build prompt via prompt_templates::build_repair_prompt
//!   3. Signal file: /tmp/sentinel-repair-<svc>-<ts>
//!   4. `python3 relay.py <pane> "" "claude -p <shlex-quoted prompt>" --no-forward --signal <signal>`
//!   5. repair_loop polls signal file (async) — success if no "error" substring
//!
//! Timeout default: 600s. Managed by Remediator.active_jobs map.

use crate::models::now_epoch;
use crate::prompt_templates::build_repair_prompt;
use dashmap::DashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::process::Command;
use tokio::time::timeout;

const PANE_POOL_SCRIPT: &str = "/Users/joneshong/.claude/skills/tmux-relay/scripts/pane_pool.py";
const RELAY_SCRIPT: &str = "/Users/joneshong/.claude/skills/tmux-relay/scripts/relay.py";
const PYTHON3: &str = "/Users/joneshong/.local/bin/python3";
const SIGNAL_DIR: &str = "/tmp";
const ACQUIRE_TIMEOUT_SEC: u64 = 15;
const DISPATCH_TIMEOUT_SEC: u64 = 60;
pub const DEFAULT_REPAIR_TIMEOUT_SEC: f64 = 600.0;

#[derive(Debug, Clone)]
pub struct RepairJob {
    pub service: String,
    pub pane: String,
    pub signal_file: PathBuf,
    pub started_at: f64,
    pub timeout_sec: f64,
}

pub enum Outcome {
    Dispatched(String),
    PaneUnavailable,
    #[allow(dead_code)]
    Disabled,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CompletionStatus {
    Running,
    Success,
    Failure,
    Timeout,
}

#[derive(Clone)]
pub struct AiRepairEngine {
    active_jobs: Arc<DashMap<String, RepairJob>>,
}

impl Default for AiRepairEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl AiRepairEngine {
    pub fn new() -> Self {
        Self {
            active_jobs: Arc::new(DashMap::new()),
        }
    }

    pub async fn dispatch(&self, service: &str, detail: &str) -> Outcome {
        if self.active_jobs.contains_key(service) {
            tracing::warn!(service, "repair already active");
            let job = self.active_jobs.get(service).unwrap();
            return Outcome::Dispatched(job.pane.clone());
        }

        // Script presence check
        if !std::path::Path::new(PANE_POOL_SCRIPT).exists() {
            tracing::warn!("pane_pool.py missing at {}", PANE_POOL_SCRIPT);
            return Outcome::PaneUnavailable;
        }
        if !std::path::Path::new(RELAY_SCRIPT).exists() {
            tracing::warn!("relay.py missing at {}", RELAY_SCRIPT);
            return Outcome::PaneUnavailable;
        }

        // Acquire pane
        let pane = match acquire_pane().await {
            Some(p) => p,
            None => {
                tracing::error!(service, "no relay pane available");
                return Outcome::PaneUnavailable;
            }
        };

        // Build prompt + signal file path
        let prompt = build_repair_prompt(service, detail);
        let ts = now_epoch() as u64;
        let signal_file = PathBuf::from(SIGNAL_DIR)
            .join(format!("sentinel-repair-{}-{}", service, ts));

        // Dispatch via relay
        let command = format!("claude -p {}", shell_quote(&prompt));
        let dispatched = relay_dispatch(&pane, &command, &signal_file).await;

        if dispatched {
            self.active_jobs.insert(
                service.to_string(),
                RepairJob {
                    service: service.to_string(),
                    pane: pane.clone(),
                    signal_file,
                    started_at: now_epoch(),
                    timeout_sec: DEFAULT_REPAIR_TIMEOUT_SEC,
                },
            );
            tracing::info!(service, pane = %pane, "repair dispatched");
            Outcome::Dispatched(pane)
        } else {
            tracing::error!(service, "relay dispatch failed");
            Outcome::PaneUnavailable
        }
    }

    pub fn check_completion(&self, service: &str) -> Option<CompletionStatus> {
        let job = self.active_jobs.get(service)?.clone();

        if job.signal_file.exists() {
            let result = std::fs::read_to_string(&job.signal_file)
                .unwrap_or_default()
                .trim()
                .to_string();
            let _ = std::fs::remove_file(&job.signal_file);
            self.active_jobs.remove(service);
            tracing::info!(service, result = %result, "repair completed");
            return Some(if result.to_lowercase().contains("error") {
                CompletionStatus::Failure
            } else {
                CompletionStatus::Success
            });
        }

        if now_epoch() - job.started_at > job.timeout_sec {
            self.active_jobs.remove(service);
            tracing::warn!(service, "repair timed out");
            return Some(CompletionStatus::Timeout);
        }

        Some(CompletionStatus::Running)
    }

    pub fn active_services(&self) -> Vec<String> {
        self.active_jobs
            .iter()
            .map(|e| e.key().clone())
            .collect()
    }
}

async fn acquire_pane() -> Option<String> {
    let out = timeout(
        Duration::from_secs(ACQUIRE_TIMEOUT_SEC),
        Command::new(PYTHON3)
            .args([PANE_POOL_SCRIPT, "acquire", "1"])
            .output(),
    )
    .await;

    let Ok(Ok(out)) = out else { return None };
    if !out.status.success() {
        return None;
    }
    let pane = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if pane.is_empty() {
        None
    } else {
        Some(pane)
    }
}

async fn relay_dispatch(pane: &str, command: &str, signal_file: &std::path::Path) -> bool {
    let out = timeout(
        Duration::from_secs(DISPATCH_TIMEOUT_SEC),
        Command::new(PYTHON3)
            .args([
                RELAY_SCRIPT,
                pane,
                "",
                command,
                "--no-forward",
                "--detach",
                "--signal",
                signal_file.to_str().unwrap_or("/tmp/sentinel-repair-unknown"),
            ])
            .output(),
    )
    .await;

    matches!(out, Ok(Ok(o)) if o.status.success())
}

/// Minimal shell single-quote escape (mirrors Python shlex.quote behavior).
fn shell_quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    if s.chars().all(|c| c.is_alphanumeric() || "@%+=:,./-_".contains(c)) {
        return s.into();
    }
    // Wrap in single quotes, escape any embedded single quotes
    let escaped = s.replace('\'', "'\\''");
    format!("'{}'", escaped)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_empty() {
        assert_eq!(shell_quote(""), "''");
    }

    #[test]
    fn quotes_simple() {
        assert_eq!(shell_quote("hello"), "hello");
    }

    #[test]
    fn quotes_with_spaces() {
        assert_eq!(shell_quote("hello world"), "'hello world'");
    }

    #[test]
    fn quotes_with_single_quote() {
        assert_eq!(shell_quote("it's"), "'it'\\''s'");
    }
}
