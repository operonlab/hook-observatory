//! CPU temperature. Aligns 1:1 with Python `_collect_temperature()`.
//!
//! Apple Silicon thermal data needs sudo via powermetrics; we use
//! `osx-cpu-temp` (community CLI, brew install) which works without sudo.

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};

use super::cpu::classify_pressure;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (80.0, 95.0, 105.0);

pub async fn collect() -> Result<Value> {
    let temp_out = std::process::Command::new("osx-cpu-temp")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_default();

    let mut temp_c = 0.0_f64;
    if !temp_out.is_empty() {
        let re = Regex::new(r"([\d.]+)\s*°?C").unwrap();
        if let Some(c) = re.captures(&temp_out) {
            temp_c = c[1].parse().unwrap_or(0.0);
        }
    }

    if temp_c == 0.0 {
        return Ok(json!({
            "cpu_temp_c": Value::Null,
            "available": false,
            "pressure": "unknown",
            "note": "Install osx-cpu-temp (brew install osx-cpu-temp) for temperature monitoring",
        }));
    }

    let pressure = classify_pressure(temp_c, DEFAULT_THRESHOLDS, false);

    Ok(json!({
        "cpu_temp_c": temp_c,
        "available": true,
        "pressure": pressure,
    }))
}
