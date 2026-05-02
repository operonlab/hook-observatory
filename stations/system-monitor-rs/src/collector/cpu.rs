//! CPU metrics. Aligns 1:1 with Python `_collect_cpu()` in collector.py.
//!
//! Source of truth: `top -l 1` (user/sys/idle + load avg) + `sysctl` for
//! brand and core count. sysinfo is intentionally NOT used here because
//! Python parses `top` directly and we need byte-for-byte matching numbers.

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};

use super::Collector;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (70.0, 85.0, 95.0); // warning / critical / danger

pub async fn collect(_c: &Collector) -> Result<Value> {
    let top_out = run("top", &["-l", "1", "-n", "0"]);

    let mut user_pct = 0.0_f64;
    let mut sys_pct = 0.0_f64;
    let mut idle_pct = 0.0_f64;
    let mut load_avg: [f64; 3] = [0.0, 0.0, 0.0];

    let re_user = Regex::new(r"([\d.]+)%\s*user").unwrap();
    let re_sys = Regex::new(r"([\d.]+)%\s*sys").unwrap();
    let re_idle = Regex::new(r"([\d.]+)%\s*idle").unwrap();
    let re_num = Regex::new(r"[\d.]+").unwrap();

    for line in top_out.lines() {
        if line.contains("CPU usage") {
            if let Some(c) = re_user.captures(line) {
                user_pct = parse_f64(&c[1]);
            }
            if let Some(c) = re_sys.captures(line) {
                sys_pct = parse_f64(&c[1]);
            }
            if let Some(c) = re_idle.captures(line) {
                idle_pct = parse_f64(&c[1]);
            }
        }
        if line.contains("Load Avg") {
            let nums: Vec<f64> = re_num.find_iter(line).map(|m| parse_f64(m.as_str())).collect();
            for (i, v) in nums.iter().take(3).enumerate() {
                load_avg[i] = *v;
            }
        }
    }

    let usage_pct = round1(user_pct + sys_pct);

    let core_count_str = run("sysctl", &["-n", "hw.logicalcpu"]);
    let cores: u64 = core_count_str.trim().parse().unwrap_or(0);

    let cpu_brand = brand().unwrap_or_default();

    let pressure = classify_pressure(usage_pct, DEFAULT_THRESHOLDS, false);

    Ok(json!({
        "brand": cpu_brand,
        "cores": cores,
        "usage_pct": usage_pct,
        "user_pct": user_pct,
        "sys_pct": sys_pct,
        "idle_pct": idle_pct,
        "load_avg_1m": load_avg[0],
        "load_avg_5m": load_avg[1],
        "load_avg_15m": load_avg[2],
        "pressure": pressure,
    }))
}

/// Returns `machdep.cpu.brand_string` via sysctl, e.g. "Apple M2 Pro".
pub fn brand() -> Result<String> {
    let out = std::process::Command::new("sysctl")
        .args(["-n", "machdep.cpu.brand_string"])
        .output()?;
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn run(cmd: &str, args: &[&str]) -> String {
    std::process::Command::new(cmd)
        .args(args)
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_default()
}

fn parse_f64(s: &str) -> f64 {
    s.parse().unwrap_or(0.0)
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

pub(crate) fn classify_pressure(value: f64, thresholds: (f64, f64, f64), invert: bool) -> &'static str {
    let (w, c, d) = thresholds;
    if invert {
        if value <= d {
            "danger"
        } else if value <= c {
            "critical"
        } else if value <= w {
            "warning"
        } else {
            "normal"
        }
    } else if value >= d {
        "danger"
    } else if value >= c {
        "critical"
    } else if value >= w {
        "warning"
    } else {
        "normal"
    }
}
