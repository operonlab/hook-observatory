//! Memory metrics. Aligns 1:1 with Python `_collect_memory()`.
//!
//! Strategy mirrors Python:
//!   - total = sysctl hw.memsize
//!   - vm_stat for active/inactive/speculative/wired/compressed pages
//!   - app_bytes = (active + wired + compressed) * page_size
//!   - usage_pct = app_bytes * 100 / total
//!   - system_pressure from `memory_pressure` first line

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};

use super::Collector;
use super::cpu::classify_pressure;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (75.0, 85.0, 95.0);

pub async fn collect(_c: &Collector) -> Result<Value> {
    let mem_str = run("sysctl", &["-n", "hw.memsize"]);
    let total_bytes: u64 = mem_str.trim().parse().unwrap_or(0);
    let total_gb = round1(total_bytes as f64 / GB);

    let vm_out = run("vm_stat", &[]);
    let mut page_size: u64 = 16384; // Apple Silicon default
    let re_ps = Regex::new(r"page size of (\d+) bytes").unwrap();
    if let Some(c) = re_ps.captures(&vm_out) {
        page_size = c[1].parse().unwrap_or(16384);
    }

    let active = pages(&vm_out, "Pages active");
    let _inactive = pages(&vm_out, "Pages inactive");
    let _speculative = pages(&vm_out, "Pages speculative");
    let wired = pages(&vm_out, "Pages wired down");
    let compressed = pages(&vm_out, "Pages occupied by compressor");

    let app_bytes = (active + wired + compressed) * page_size;
    let app_gb = round1(app_bytes as f64 / GB);
    let used_gb = app_gb;

    let usage_pct = if total_bytes > 0 {
        round1(app_bytes as f64 * 100.0 / total_bytes as f64)
    } else {
        0.0
    };

    let pressure_out = run("memory_pressure", &[]);
    let first_line = pressure_out.lines().next().unwrap_or("").to_lowercase();
    let sys_pressure = if first_line.contains("critical") {
        "critical"
    } else if first_line.contains("warn") {
        "warning"
    } else {
        "normal"
    };

    let pressure = classify_pressure(usage_pct, DEFAULT_THRESHOLDS, false);

    Ok(json!({
        "total_gb": total_gb,
        "used_gb": used_gb,
        "app_gb": app_gb,
        "wired_gb": round1(wired as f64 * page_size as f64 / GB),
        "compressed_gb": round1(compressed as f64 * page_size as f64 / GB),
        "usage_pct": usage_pct,
        "system_pressure": sys_pressure,
        "pressure": pressure,
    }))
}

const GB: f64 = 1024.0 * 1024.0 * 1024.0;

fn run(cmd: &str, args: &[&str]) -> String {
    std::process::Command::new(cmd)
        .args(args)
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_default()
}

fn pages(vm_out: &str, label: &str) -> u64 {
    let re = Regex::new(&format!(r"{}:\s+(\d+)", regex::escape(label))).unwrap();
    re.captures(vm_out)
        .and_then(|c| c[1].parse::<u64>().ok())
        .unwrap_or(0)
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}
