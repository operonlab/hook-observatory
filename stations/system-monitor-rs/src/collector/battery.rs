//! Battery info. Aligns 1:1 with Python `_collect_battery()`.
//!
//! Strategy mirrors Python:
//!   - Detect via `pmset -g batt` ("InternalBattery" or "Battery" string)
//!   - Parse percent + charging
//!   - Cycle count + condition from `system_profiler SPPowerDataType`
//!
//! Note: prefer shell-out over `battery` crate so output matches Python
//! semantics (especially the "no battery → available=false" branch).

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};

use super::cpu::classify_pressure;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (30.0, 20.0, 10.0); // warning/critical/danger (invert)

pub fn collect() -> Result<Value> {
    let batt_out = run("pmset", &["-g", "batt"]);

    if !batt_out.contains("InternalBattery") && !batt_out.contains("Battery") {
        return Ok(json!({
            "available": false,
            "note": "No battery detected (desktop Mac)",
        }));
    }

    let mut pct: i64 = 0;
    let re_pct = Regex::new(r"(\d+)%").unwrap();
    if let Some(c) = re_pct.captures(&batt_out) {
        pct = c[1].parse().unwrap_or(0);
    }

    let lower = batt_out.to_lowercase();
    let charging = lower.contains("charging") && !lower.contains("not charging");

    // Battery condition + cycle count from system_profiler
    let sp_out = run("system_profiler", &["SPPowerDataType"]);
    let mut cycle_count: Option<i64> = None;
    let mut condition: Option<String> = None;
    for line in sp_out.lines() {
        if line.contains("Cycle Count") {
            let re = Regex::new(r"(\d+)").unwrap();
            if let Some(c) = re.captures(line) {
                cycle_count = c[1].parse().ok();
            }
        }
        if line.contains("Condition") {
            condition = line.split(':').nth(1).map(|s| s.trim().to_string());
        }
    }

    let pressure = classify_pressure(pct as f64, DEFAULT_THRESHOLDS, true);

    Ok(json!({
        "available": true,
        "percent": pct,
        "charging": charging,
        "cycle_count": cycle_count,
        "condition": condition,
        "pressure": pressure,
    }))
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
