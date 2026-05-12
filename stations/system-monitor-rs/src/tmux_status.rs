//! tmux status line — single line, stdout-only, NO tracing log.
//!
//! Mirrors `stations/system-monitor/tmux_status.py`. Read order:
//!   1. /tmp/agent-metrics-sysmon.json (primary, fast path)
//!   2. HTTP fallback (timeout 1s)
//!   3. "─" placeholder
//!
//! Two top-level kinds dispatched by main.rs:
//!   - "system" → compact `CPU 12% │ MEM 45% │ DISK 67%`
//!   - "llm"    → compact LLM quota glance
//!
//! All 13 sub-metric names from the Python version are also accepted as `kind`
//! so existing tmux.conf `#(... <metric>)` calls keep working.

use anyhow::Result;
use serde_json::Value;
use std::path::Path;
use std::time::Duration;

use crate::config::Settings;

const PRIMARY: &str = "/tmp/agent-metrics-sysmon.json";
const PLACEHOLDER: &str = "─";

/// Map the user-facing metric name to the JSON field written by agent-metrics.
fn field_map(metric: &str) -> Option<&'static str> {
    match metric {
        // System metrics
        "cpu" => Some("cpu_display"),
        "mem" => Some("mem_display"),
        "net" => Some("net_display"),
        "disk" => Some("disk_display"),
        "cc" => Some("cc_display"),
        "pressure" => Some("mem_pressure"),
        // LLM quota metrics
        "cc-5h" => Some("llm_cc_5h"),
        "cc-7d" => Some("llm_cc_7d"),
        "cc-ex" => Some("llm_cc_ex"),
        "cx-5h" => Some("llm_cx_5h"),
        "cx-7d" => Some("llm_cx_7d"),
        "gm-pro" => Some("llm_gm_pro"),
        "gm-flash" => Some("llm_gm_flash"),
        _ => None,
    }
}

fn is_quota(metric: &str) -> bool {
    matches!(
        metric,
        "cc-5h" | "cc-7d" | "cc-ex" | "cx-5h" | "cx-7d" | "gm-pro" | "gm-flash"
    )
}

/// CLI entrypoint. `kind` may be a top-level mode (`system`/`llm`) or a
/// specific sub-metric (e.g. `cpu`, `cc-ex`).
pub async fn print(_cfg: &Settings, kind: &str) -> Result<()> {
    let line = match kind {
        "system" => render_system().await,
        "llm" => render_llm().await,
        // Pass-through single sub-metric.
        other => get_metric(other).await,
    };
    print!("{line}");
    Ok(())
}

async fn render_system() -> String {
    let cpu = get_metric("cpu").await;
    let mem = get_metric("mem").await;
    let disk = get_metric("disk").await;
    format!("CPU {cpu} │ MEM {mem} │ DISK {disk}")
}

async fn render_llm() -> String {
    let cc5 = get_metric("cc-5h").await;
    let cc7 = get_metric("cc-7d").await;
    let ex = get_metric("cc-ex").await;
    if ex == PLACEHOLDER || ex.is_empty() || ex == "off" {
        format!("CC5 {cc5} │ CC7 {cc7}")
    } else {
        format!("CC5 {cc5} │ CC7 {cc7} │ EX {ex}")
    }
}

/// Read a single metric value, walking the file → HTTP → placeholder chain.
async fn get_metric(metric: &str) -> String {
    let Some(field) = field_map(metric) else {
        return PLACEHOLDER.to_string();
    };

    let max_age_secs = if is_quota(metric) { 120.0 } else { 15.0 };
    if let Some(v) = read_from_file(field, max_age_secs) {
        return v;
    }
    if let Some(v) = read_from_api(metric, field).await {
        return v;
    }
    PLACEHOLDER.to_string()
}

fn file_age_secs(path: &Path) -> f64 {
    match std::fs::metadata(path).and_then(|m| m.modified()) {
        Ok(mtime) => mtime
            .elapsed()
            .map(|d| d.as_secs_f64())
            .unwrap_or(f64::INFINITY),
        Err(_) => f64::INFINITY,
    }
}

fn read_from_file(field: &str, max_age: f64) -> Option<String> {
    let path = Path::new(PRIMARY);
    if !path.exists() {
        return None;
    }
    if file_age_secs(path) > max_age {
        return None;
    }
    let raw = std::fs::read_to_string(path).ok()?;
    let data: Value = serde_json::from_str(&raw).ok()?;
    let val = data.get(field)?;
    let s = match val {
        Value::String(s) => s.clone(),
        Value::Null => return None,
        v => v.to_string(),
    };
    if s.is_empty() || s == "None" {
        return None;
    }
    Some(s)
}

async fn read_from_api(metric: &str, field: &str) -> Option<String> {
    // Port resolved from shared/schemas/port_registry.yaml (codegen at build time).
    // Falls back to 10103 if yaml is missing the entry so the binary stays bootable.
    let port = workshop_port_registry::get("agent-metrics")
        .map(|s| s.port)
        .unwrap_or(10103);
    let (url, key) = if is_quota(metric) {
        (format!("http://127.0.0.1:{port}/quota/formatted"), metric)
    } else {
        (format!("http://127.0.0.1:{port}/sysmon/current"), field)
    };
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .ok()?;
    let resp = client.get(&url).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let data: Value = resp.json().await.ok()?;
    let val = data.get(key)?;
    let s = match val {
        Value::String(s) => s.clone(),
        Value::Null => return None,
        v => v.to_string(),
    };
    if s.is_empty() || s == "None" {
        return None;
    }
    Some(s)
}
