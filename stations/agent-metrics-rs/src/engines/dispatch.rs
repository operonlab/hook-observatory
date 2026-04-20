//! CLI dispatch — shells out to claude/codex/gemini headless wrappers.
//!
//! Mirrors `dispatch_agent` / `dispatch_relay` / `dispatch_fleet` in Python.
//! Relay and fleet are best-effort HTTP integrations; if their respective
//! services are unavailable, callers fall back via `routing::resolve_tier`
//! (already invoked in the route handler).

use crate::config::Settings;
use serde::Serialize;
use std::path::PathBuf;
use std::time::{Duration, Instant};
use tokio::process::Command;

#[derive(Debug, Clone, Serialize)]
pub struct AgentResult {
    pub task_id: String,
    pub cli: String,
    pub status: String,
    pub duration_s: f64,
    pub output: String,
}

impl AgentResult {
    fn fail(task_id: String, cli: &str, msg: impl Into<String>, started: Instant) -> Self {
        Self {
            task_id,
            cli: cli.into(),
            status: "failed".into(),
            duration_s: round1(started.elapsed().as_secs_f64()),
            output: msg.into(),
        }
    }
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

fn now_id_for(cli: &str) -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{cli}-{secs}")
}

fn build_headless_paths(skills_dir: &str) -> [(String, PathBuf); 3] {
    let sd = PathBuf::from(skills_dir);
    [
        ("claude".into(), sd.join("claude-code-headless").join("scripts").join("claude_headless.py")),
        ("codex".into(),  sd.join("codex-cli-headless").join("scripts").join("codex_headless.py")),
        ("gemini".into(), sd.join("gemini-cli-headless").join("scripts").join("gemini_headless.py")),
    ]
}

fn script_for(cli: &str, skills_dir: &str) -> Option<PathBuf> {
    build_headless_paths(skills_dir)
        .into_iter()
        .find(|(name, _)| name == cli)
        .map(|(_, p)| p)
}

fn python_bin() -> String {
    std::env::var("AGENT_METRICS_PYTHON_BIN")
        .unwrap_or_else(|_| {
            std::env::var("HOME")
                .map(|h| format!("{h}/.local/bin/python3"))
                .unwrap_or_else(|_| "/usr/bin/python3".into())
        })
}

pub async fn dispatch_agent(
    settings: &Settings,
    cli: &str,
    prompt: &str,
    cwd: Option<&str>,
    timeout_s: u64,
) -> AgentResult {
    let task_id = now_id_for(cli);
    let started = Instant::now();
    let script = match script_for(cli, &settings.skills_dir) {
        Some(s) => s,
        None => {
            return AgentResult::fail(task_id, cli, format!("Unknown CLI: {cli}"), started);
        }
    };

    let py = python_bin();
    let mut cmd = Command::new(&py);
    cmd.arg(&script);
    match cli {
        "claude" => {
            cmd.arg("-p").arg(prompt)
                .arg("--output-format").arg("json")
                .arg("--allowedTools").arg("Read,Edit,Bash");
            if let Some(c) = cwd {
                cmd.arg("--cwd").arg(c);
            }
        }
        "codex" => {
            cmd.arg("--full-auto");
            if let Some(c) = cwd {
                cmd.arg("--cd").arg(c);
            }
            cmd.arg(prompt);
        }
        "gemini" => {
            cmd.arg("-p").arg(prompt)
                .arg("--approval-mode").arg("yolo");
            if let Some(c) = cwd {
                cmd.arg("--cwd").arg(c);
            }
        }
        _ => return AgentResult::fail(task_id, cli, format!("Unknown CLI: {cli}"), started),
    }

    let exec = cmd.kill_on_drop(true).output();
    let out = match tokio::time::timeout(Duration::from_secs(timeout_s), exec).await {
        Ok(Ok(o)) => o,
        Ok(Err(e)) => {
            return AgentResult::fail(task_id, cli, format!("Dispatch error: {e}"), started);
        }
        Err(_) => {
            return AgentResult {
                task_id,
                cli: cli.into(),
                status: "timeout".into(),
                duration_s: timeout_s as f64,
                output: "Agent timed out".into(),
            };
        }
    };

    let mut output = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if cli == "claude" && !output.is_empty() {
        if let Some(parsed) = strip_ansi_and_extract_json(&output) {
            if let Some(result) = parsed.get("result").and_then(|v| v.as_str()) {
                output = result.to_string();
            }
        }
    }
    output.truncate(5000);

    let status = if out.status.success() { "done" } else { "failed" };
    AgentResult {
        task_id,
        cli: cli.into(),
        status: status.into(),
        duration_s: round1(started.elapsed().as_secs_f64()),
        output,
    }
}

fn strip_ansi_and_extract_json(s: &str) -> Option<serde_json::Value> {
    // Naive ANSI strip: drop ESC[...]<letter> sequences
    let mut clean = String::with_capacity(s.len());
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == 0x1b && i + 1 < bytes.len() && bytes[i + 1] == b'[' {
            // skip until alphabetic terminator
            let mut j = i + 2;
            while j < bytes.len() && !bytes[j].is_ascii_alphabetic() {
                j += 1;
            }
            i = j.saturating_add(1);
            continue;
        }
        clean.push(bytes[i] as char);
        i += 1;
    }
    let start = clean.find('{')?;
    serde_json::from_str(&clean[start..]).ok()
}

// ── Relay / Fleet — best-effort thin clients ───────────────────

pub async fn dispatch_relay(
    prompt: &str,
    cwd: Option<&str>,
    timeout_s: u64,
) -> AgentResult {
    let task_id = format!("relay-{}", std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0));
    let started = Instant::now();
    let url = std::env::var("AGENT_METRICS_RELAY_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:10100/run".into());
    let body = serde_json::json!({
        "prompt": prompt,
        "cwd": cwd,
        "timeout": timeout_s,
    });
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(timeout_s + 30))
        .build() {
        Ok(c) => c,
        Err(e) => return AgentResult::fail(task_id, "claude", format!("Relay client init: {e}"), started),
    };
    match client.post(&url).json(&body).send().await {
        Ok(resp) => {
            let elapsed = round1(started.elapsed().as_secs_f64());
            let value: serde_json::Value = resp.json().await.unwrap_or(serde_json::Value::Null);
            let status = value.get("status").and_then(|v| v.as_str()).unwrap_or("failed");
            let output = value.get("output").and_then(|v| v.as_str()).unwrap_or("");
            AgentResult {
                task_id,
                cli: "claude".into(),
                status: if status == "completed" { "done".into() } else { status.into() },
                duration_s: elapsed,
                output: output.chars().take(5000).collect(),
            }
        }
        Err(e) => AgentResult::fail(task_id, "claude", format!("Relay error: {e}"), started),
    }
}

pub async fn dispatch_fleet(
    prompt: &str,
    timeout_s: u64,
) -> AgentResult {
    // Fleet has its own task lifecycle (dispatch + poll). Simplified: POST /tasks
    // with the prompt, poll /tasks/{id} every 5s up to timeout.
    let task_id = format!("fleet-{}", std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0));
    let started = Instant::now();
    let base = std::env::var("AGENT_METRICS_FLEET_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:10209".into());
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build() {
        Ok(c) => c,
        Err(e) => return AgentResult::fail(task_id, "claude", format!("Fleet client init: {e}"), started),
    };
    let dispatch_body = serde_json::json!({"prompt": prompt, "mode": "code", "timeout": timeout_s});
    let dispatched: serde_json::Value = match client
        .post(format!("{base}/tasks"))
        .json(&dispatch_body)
        .send()
        .await
    {
        Ok(r) => r.json().await.unwrap_or(serde_json::Value::Null),
        Err(e) => return AgentResult::fail(task_id, "claude", format!("Fleet dispatch: {e}"), started),
    };
    let fleet_id = match dispatched.get("id").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return AgentResult::fail(task_id, "claude", "Fleet: no task id", started),
    };

    let mut interval = 5_u64;
    while started.elapsed().as_secs() < timeout_s {
        tokio::time::sleep(Duration::from_secs(interval)).await;
        interval = interval.saturating_mul(2).min(30);
        let status: serde_json::Value = match client
            .get(format!("{base}/tasks/{fleet_id}"))
            .send().await
        {
            Ok(r) => r.json().await.unwrap_or(serde_json::Value::Null),
            Err(_) => continue,
        };
        let s = status.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if matches!(s, "completed" | "failed" | "timeout" | "cancelled") {
            let output = status.get("output").and_then(|v| v.as_str()).unwrap_or("").to_string();
            return AgentResult {
                task_id: format!("fleet-{fleet_id}"),
                cli: "claude".into(),
                status: if s == "completed" { "done".into() } else { s.into() },
                duration_s: round1(started.elapsed().as_secs_f64()),
                output: output.chars().take(5000).collect(),
            };
        }
    }
    AgentResult {
        task_id,
        cli: "claude".into(),
        status: "timeout".into(),
        duration_s: timeout_s as f64,
        output: "Fleet task timed out".into(),
    }
}

pub async fn dispatch_by_tier(
    settings: &Settings,
    tier: &str,
    cli: &str,
    prompt: &str,
    cwd: Option<&str>,
    timeout_s: u64,
) -> AgentResult {
    match tier {
        "fleet" => dispatch_fleet(prompt, timeout_s).await,
        "relay" => dispatch_relay(prompt, cwd, timeout_s).await,
        _ => dispatch_agent(settings, cli, prompt, cwd, timeout_s).await,
    }
}
