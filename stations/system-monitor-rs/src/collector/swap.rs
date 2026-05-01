//! Swap usage via `sysctl vm.swapusage`. Aligns 1:1 with Python `_collect_swap()`.

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};

use super::Collector;
use super::cpu::classify_pressure;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (2.0, 4.0, 8.0); // GB

pub async fn collect(_c: &Collector) -> Result<Value> {
    let raw = std::process::Command::new("sysctl")
        .args(["-n", "vm.swapusage"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .unwrap_or_default();

    // Example: "total = 6144.00M  used = 1234.50M  free = 4909.50M  (encrypted)"
    let re_total = Regex::new(r"total\s*=\s*([\d.]+)M").unwrap();
    let re_used = Regex::new(r"used\s*=\s*([\d.]+)M").unwrap();

    let total_mb = re_total
        .captures(&raw)
        .and_then(|c| c[1].parse::<f64>().ok())
        .unwrap_or(0.0);
    let used_mb = re_used
        .captures(&raw)
        .and_then(|c| c[1].parse::<f64>().ok())
        .unwrap_or(0.0);

    let used_gb = round2(used_mb / 1024.0);
    let total_gb = round2(total_mb / 1024.0);

    let pressure = classify_pressure(used_gb, DEFAULT_THRESHOLDS, false);

    Ok(json!({
        "total_gb": total_gb,
        "used_gb": used_gb,
        "pressure": pressure,
    }))
}

fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}
