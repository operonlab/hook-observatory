//! Top processes. Aligns 1:1 with Python `collect_top_processes()`.
//!
//! Strategy mirrors Python: shell out to `ps -eo pid,pcpu,pmem,rss,comm -r`
//! and aggregate by basename. Sort by `cpu_pct + mem_pct`, return top N.
//!
//! Why ps over sysinfo: macOS ps `pcpu` is the kernel's instantaneous %
//! that Activity Monitor shows. sysinfo's CPU usage uses a different
//! sampling window and won't match Python output verbatim.

use anyhow::Result;
use serde_json::{json, Value};
use std::collections::HashMap;

use super::Collector;

const TOP_N: usize = 3;

#[derive(Clone)]
struct Agg {
    name: String,
    pid: i64,
    cpu_pct: f64,
    mem_pct: f64,
    mem_mb: f64,
    count: u32,
}

fn aggregate() -> Vec<Agg> {
    let out = std::process::Command::new("ps")
        .args(["-eo", "pid,pcpu,pmem,rss,comm", "-r"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .unwrap_or_default();

    let mut by_name: HashMap<String, Agg> = HashMap::new();
    // Skip header, take up to 30 rows like Python's `head -30`.
    for line in out.lines().skip(1).take(29) {
        // Python uses str.split(None, 4) — split on whitespace, max 5 fields,
        // last field keeps the rest verbatim. Rust's `splitn` doesn't collapse
        // runs of whitespace, so we use a manual helper.
        let parts = split_ws_n(line, 5);
        if parts.len() < 5 {
            continue;
        }
        let pid: i64 = parts[0].parse().unwrap_or(0);
        let cpu: f64 = parts[1].parse().unwrap_or(0.0);
        let mem_pct: f64 = parts[2].parse().unwrap_or(0.0);
        let rss_kb: u64 = parts[3].parse().unwrap_or(0);
        let comm = parts[4].rsplit('/').next().unwrap_or(&parts[4]).to_string();

        let entry = by_name.entry(comm.clone()).or_insert(Agg {
            name: comm,
            pid,
            cpu_pct: 0.0,
            mem_pct: 0.0,
            mem_mb: 0.0,
            count: 0,
        });
        entry.cpu_pct += cpu;
        entry.mem_pct += mem_pct;
        entry.mem_mb += rss_kb as f64 / 1024.0;
        entry.count += 1;
    }

    by_name.into_values().collect()
}

/// Splits a line on whitespace into at most `n` parts (last part keeps the
/// remainder verbatim), matching Python's `str.split(None, n-1)` semantics.
fn split_ws_n(line: &str, n: usize) -> Vec<String> {
    let mut out: Vec<String> = Vec::with_capacity(n);
    let mut rest = line.trim_start();
    while out.len() + 1 < n {
        match rest.find(char::is_whitespace) {
            Some(idx) => {
                out.push(rest[..idx].to_string());
                rest = rest[idx..].trim_start();
            }
            None => break,
        }
    }
    if !rest.is_empty() {
        out.push(rest.to_string());
    }
    out
}

fn to_value(a: &Agg) -> Value {
    json!({
        "name": a.name,
        "pid": a.pid,
        "cpu_pct": round1(a.cpu_pct),
        "mem_pct": round1(a.mem_pct),
        "mem_mb": round1(a.mem_mb),
        "count": a.count,
    })
}

/// Top processes sorted by combined CPU + memory weight. Matches Python
/// `collect_top_processes()` 1:1 (single list, top 3).
pub async fn top_by_cpu_and_mem(_c: &Collector) -> Result<Vec<Value>> {
    let mut entries = aggregate();
    entries.sort_by(|a, b| {
        (b.cpu_pct + b.mem_pct)
            .partial_cmp(&(a.cpu_pct + a.mem_pct))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    Ok(entries.iter().take(TOP_N).map(to_value).collect())
}

/// Variant: returns (top_by_cpu, top_by_mem). Not used by mod.rs today, but
/// available for future endpoints that want each axis separately.
#[allow(dead_code)]
pub async fn top_split(_c: &Collector) -> Result<(Vec<Value>, Vec<Value>)> {
    let entries = aggregate();
    let mut by_cpu = entries.clone();
    by_cpu.sort_by(|a, b| b.cpu_pct.partial_cmp(&a.cpu_pct).unwrap_or(std::cmp::Ordering::Equal));
    let mut by_mem = entries;
    by_mem.sort_by(|a, b| b.mem_pct.partial_cmp(&a.mem_pct).unwrap_or(std::cmp::Ordering::Equal));
    Ok((
        by_cpu.iter().take(TOP_N).map(to_value).collect(),
        by_mem.iter().take(TOP_N).map(to_value).collect(),
    ))
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}
