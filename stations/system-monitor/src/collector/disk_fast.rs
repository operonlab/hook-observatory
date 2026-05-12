//! Fast disk metrics. Aligns 1:1 with Python `collect_disk_fast()`.
//!
//! Strategy mirrors Python:
//!   1. Primary: `df -k /System/Volumes/Data | tail -1` (most accurate on APFS)
//!   2. Fallback: `diskutil apfs list` parse "Size (Capacity Ceiling)" /
//!      "Capacity Not Allocated" — pick the largest container.

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};

use super::Collector;
use super::cpu::classify_pressure;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (75.0, 85.0, 95.0);

pub async fn collect(_c: &Collector) -> Result<Value> {
    let mut total_bytes: u64 = 0;
    let mut free_bytes: u64 = 0;

    // Primary: df -k on Data volume
    if let Some(out) = run_str("df", &["-k", "/System/Volumes/Data"]) {
        if let Some(line) = out.lines().last() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                if let (Ok(t), Ok(f)) = (parts[1].parse::<u64>(), parts[3].parse::<u64>()) {
                    total_bytes = t * 1024;
                    free_bytes = f * 1024;
                }
            }
        }
    }

    // Fallback: APFS container scan
    if total_bytes == 0 {
        if let Some(container_raw) = run_str("diskutil", &["apfs", "list"]) {
            let re_size = Regex::new(r"(\d+)\s*B\b").unwrap();
            let mut max_total: u64 = 0;
            let mut cur_total: u64 = 0;
            for line in container_raw.lines() {
                if line.contains("Size (Capacity Ceiling)") {
                    if let Some(c) = re_size.captures(line) {
                        cur_total = c[1].parse().unwrap_or(0);
                    }
                } else if line.contains("Capacity Not Allocated") {
                    if let Some(c) = re_size.captures(line) {
                        let cur_free: u64 = c[1].parse().unwrap_or(0);
                        if cur_total > max_total {
                            max_total = cur_total;
                            total_bytes = cur_total;
                            free_bytes = cur_free;
                        }
                    }
                }
            }
        }
    }

    let used_bytes = total_bytes.saturating_sub(free_bytes);
    let usage_pct = if total_bytes > 0 {
        round1(used_bytes as f64 * 100.0 / total_bytes as f64)
    } else {
        0.0
    };
    let pressure = classify_pressure(usage_pct, DEFAULT_THRESHOLDS, false);

    Ok(json!({
        "usage_pct": usage_pct,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "pressure_level": pressure,
    }))
}

fn run_str(cmd: &str, args: &[&str]) -> Option<String> {
    std::process::Command::new(cmd)
        .args(args)
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}
