//! System metrics collection. Replaces `stations/system-monitor/collector.py`.
//!
//! Public API: `collect_all(&Collector)` returns a JSON snapshot whose schema
//! matches the Python version 1:1 so existing dashboards / SDK clients keep
//! working through the swap.

pub mod cpu;
pub mod memory;
pub mod swap;
pub mod temperature;
pub mod battery;
pub mod disk_fast;
pub mod disk_deep;
pub mod processes;
pub mod services;

use anyhow::Result;
use serde_json::{json, Value};
use sysinfo::{System, RefreshKind, CpuRefreshKind, MemoryRefreshKind};
use tokio::sync::Mutex;
use std::sync::Arc;

/// Long-lived collector handle. `sysinfo::System` keeps prior CPU samples,
/// so we keep one instance behind a Mutex and refresh in place.
pub struct Collector {
    sys: Arc<Mutex<System>>,
}

impl Collector {
    pub fn new() -> Self {
        let mut sys = System::new_with_specifics(
            RefreshKind::new()
                .with_cpu(CpuRefreshKind::everything())
                .with_memory(MemoryRefreshKind::everything()),
        );
        sys.refresh_all();
        Self { sys: Arc::new(Mutex::new(sys)) }
    }

    pub async fn refresh(&self) {
        let mut s = self.sys.lock().await;
        s.refresh_all();
    }

    pub fn sys(&self) -> Arc<Mutex<System>> {
        self.sys.clone()
    }
}

impl Default for Collector {
    fn default() -> Self {
        Self::new()
    }
}

/// Full snapshot. Top-level shape matches Python `collect_all()`:
///   { timestamp, hostname, os_version, chip, disk, hardware,
///     pressure_level, top_processes }
pub async fn collect_all(c: &Collector) -> Result<Value> {
    c.refresh().await;
    let now = chrono::Utc::now().to_rfc3339();
    let hostname = collect_hostname();

    let hardware = collect_hardware(c).await?;
    let disk = disk_fast::collect(c).await.unwrap_or_else(|_| json!({}));
    let top_processes = processes::top_by_cpu_and_mem(c).await.unwrap_or_default();
    let pressure_level = overall_pressure(&disk, &hardware);
    let os_version = collect_os_version();
    let chip = cpu::brand().unwrap_or_default();

    Ok(json!({
        "timestamp": now,
        "hostname": hostname,
        "os_version": os_version,
        "chip": chip,
        "disk": disk,
        "hardware": hardware,
        "pressure_level": pressure_level,
        "top_processes": top_processes,
    }))
}

pub async fn collect_hardware(c: &Collector) -> Result<Value> {
    Ok(json!({
        "cpu": cpu::collect(c).await.unwrap_or_else(|_| json!({})),
        "memory": memory::collect(c).await.unwrap_or_else(|_| json!({})),
        "swap": swap::collect(c).await.unwrap_or_else(|_| json!({})),
        "temperature": temperature::collect().await.unwrap_or_else(|_| json!({"available": false})),
        "battery": battery::collect().unwrap_or_else(|_| json!({})),
    }))
}

/// Mirrors Python `overall_pressure()`: pick the worst level across disk +
/// 5 hardware sub-metrics. Python's `disk` uses key `pressure`, while the
/// fast disk schema uses `pressure_level` — we read both keys so the same
/// helper works whether `collect_all` was called with deep disk or fast disk.
fn overall_pressure(disk: &Value, hardware: &Value) -> &'static str {
    fn level(s: Option<&str>) -> u8 {
        match s.unwrap_or("normal") {
            "danger" => 3,
            "critical" => 2,
            "warning" => 1,
            _ => 0,
        }
    }
    let disk_p = disk
        .get("pressure")
        .and_then(|v| v.as_str())
        .or_else(|| disk.get("pressure_level").and_then(|v| v.as_str()));
    let mut worst = level(disk_p);
    for key in ["cpu", "memory", "swap", "temperature", "battery"] {
        let p = hardware.get(key).and_then(|h| h.get("pressure")).and_then(|v| v.as_str());
        worst = worst.max(level(p));
    }
    match worst {
        3 => "danger",
        2 => "critical",
        1 => "warning",
        _ => "normal",
    }
}

fn collect_os_version() -> String {
    std::process::Command::new("sw_vers")
        .arg("-productVersion")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_default()
}

fn collect_hostname() -> String {
    // Python uses `hostname -s` (short form). Match that to keep snapshots
    // line up across the rewrite.
    std::process::Command::new("hostname")
        .arg("-s")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .or_else(|| std::env::var("HOSTNAME").ok())
        .unwrap_or_else(|| "unknown".to_string())
}
