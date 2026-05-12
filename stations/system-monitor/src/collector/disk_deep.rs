//! Deep disk scan. Aligns 1:1 with Python `collect_disk()`.
//!
//! Implementation strategy:
//!   - Volume / capacity summary: same df + diskutil fallback as disk_fast,
//!     plus APFS volume "Capacity Consumed" parsing.
//!   - top_consumers: depth=1 children of $HOME, walked with walkdir, total
//!     size aggregated per child. Per-child wall-clock cap of 10s.
//!   - large_files / stale_files: single walkdir pass over $HOME, filter by
//!     min size + access age, with global wall-clock cap of 10s.
//!   - caches: a fixed list of cache-style dirs, sized via a bounded walkdir.
//!
//! Defaults match Python's collector config: min_mb=10, stale_days=90, top_n=30.

use anyhow::Result;
use regex::Regex;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::time::{Instant, Duration, SystemTime};
use walkdir::WalkDir;

use super::cpu::classify_pressure;

const DEFAULT_THRESHOLDS: (f64, f64, f64) = (75.0, 85.0, 95.0);
const GB: f64 = 1024.0 * 1024.0 * 1024.0;
const MB: f64 = 1024.0 * 1024.0;

const SCAN_BUDGET: Duration = Duration::from_secs(10);
const PER_DIR_BUDGET: Duration = Duration::from_secs(10);

const MIN_MB: u64 = 10;
const STALE_DAYS: i64 = 90;
const TOP_N: usize = 30;
const TOP_DIR_N: usize = 10;
const EXCLUDES: &[&str] = &[".Trash", ".git", "node_modules"];

pub async fn collect() -> Result<Value> {
    // ── Capacity summary (df → APFS fallback) ─────────────────────────────
    let (total_bytes, free_bytes) = capacity_bytes();
    let used_bytes = total_bytes.saturating_sub(free_bytes);
    let total_gb = round1(total_bytes as f64 / GB);
    let used_gb = round1(used_bytes as f64 / GB);
    let free_gb = round1(free_bytes as f64 / GB);
    let usage_pct = if total_bytes > 0 {
        round1(used_bytes as f64 * 100.0 / total_bytes as f64)
    } else {
        0.0
    };

    // ── APFS volume distribution ──────────────────────────────────────────
    let mut volumes = apfs_volumes();
    volumes.sort_by(|a, b| {
        b.get("used_gb").and_then(|v| v.as_f64()).unwrap_or(0.0)
            .partial_cmp(&a.get("used_gb").and_then(|v| v.as_f64()).unwrap_or(0.0))
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let home = home_dir();

    // ── Top consumers ─────────────────────────────────────────────────────
    let top_consumers = scan_top_dirs(&home, TOP_DIR_N);

    // ── Large + stale files (single walk) ────────────────────────────────
    let (large_files, stale_files) = scan_files(&home, MIN_MB, STALE_DAYS, TOP_N);

    // ── Caches ────────────────────────────────────────────────────────────
    let caches = scan_caches(&home);

    let pressure = classify_pressure(usage_pct, DEFAULT_THRESHOLDS, false);
    let scan_complete = !large_files.is_empty() || !top_consumers.is_empty();

    Ok(json!({
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "usage_pct": usage_pct,
        "pressure": pressure,
        "volumes": volumes.into_iter().take(10).collect::<Vec<_>>(),
        "top_consumers": top_consumers,
        "large_files": large_files,
        "stale_files": stale_files,
        "caches": caches,
        "scan_complete": scan_complete,
    }))
}

// ── Capacity helpers ─────────────────────────────────────────────────────────

fn capacity_bytes() -> (u64, u64) {
    let mut total: u64 = 0;
    let mut free: u64 = 0;
    if let Some(out) = run_str("df", &["-k", "/System/Volumes/Data"]) {
        if let Some(line) = out.lines().last() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                if let (Ok(t), Ok(f)) = (parts[1].parse::<u64>(), parts[3].parse::<u64>()) {
                    total = t * 1024;
                    free = f * 1024;
                }
            }
        }
    }
    if total == 0 {
        if let Some(raw) = run_str("diskutil", &["apfs", "list"]) {
            let re_size = Regex::new(r"(\d+)\s*B\b").unwrap();
            let mut max_total: u64 = 0;
            let mut cur_total: u64 = 0;
            for line in raw.lines() {
                if line.contains("Size (Capacity Ceiling)") {
                    if let Some(c) = re_size.captures(line) {
                        cur_total = c[1].parse().unwrap_or(0);
                    }
                } else if line.contains("Capacity Not Allocated") {
                    if let Some(c) = re_size.captures(line) {
                        let cur_free: u64 = c[1].parse().unwrap_or(0);
                        if cur_total > max_total {
                            max_total = cur_total;
                            total = cur_total;
                            free = cur_free;
                        }
                    }
                }
            }
        }
    }
    (total, free)
}

fn apfs_volumes() -> Vec<Value> {
    let raw = match run_str("diskutil", &["apfs", "list"]) {
        Some(s) => s,
        None => return Vec::new(),
    };
    let re_name = Regex::new(r"Name:\s+(.+?)(?:\s+\(Case|$)").unwrap();
    let re_cap = Regex::new(r"Capacity Consumed:\s+(\d+)\s*B\b").unwrap();
    let mut out = Vec::new();
    let mut vol_name = String::new();
    for line in raw.lines() {
        if let Some(c) = re_name.captures(line) {
            vol_name = c[1].trim().to_string();
        }
        if let Some(c) = re_cap.captures(line) {
            if !vol_name.is_empty() {
                let cap_bytes: u64 = c[1].parse().unwrap_or(0);
                out.push(json!({
                    "name": vol_name,
                    "used_gb": round1(cap_bytes as f64 / GB),
                }));
                vol_name.clear();
            }
        }
    }
    out
}

// ── Top consumers (home dir depth=1) ─────────────────────────────────────────

fn scan_top_dirs(home: &Path, top_n: usize) -> Vec<Value> {
    let mut entries: Vec<(String, f64, bool)> = Vec::new(); // (path, size_gb, timed_out)

    let read = match std::fs::read_dir(home) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    for child in read.flatten() {
        let p = child.path();
        // Skip dotfiles like Python's `ls -1d $HOME/* $HOME/.[!.]*` — Python
        // includes "."-prefixed dirs except `.` and `..`. We do the same.
        let name = match p.file_name().and_then(|n| n.to_str()) {
            Some(s) => s,
            None => continue,
        };
        if name == "." || name == ".." {
            continue;
        }
        let started = Instant::now();
        let mut total: u64 = 0;
        let mut timed_out = false;
        for entry in WalkDir::new(&p).follow_links(false).into_iter().filter_map(|e| e.ok()) {
            if started.elapsed() > PER_DIR_BUDGET {
                timed_out = true;
                break;
            }
            if let Ok(meta) = entry.metadata() {
                if meta.is_file() {
                    total = total.saturating_add(meta.len());
                }
            }
        }
        let display = format!("~/{}", name);
        if timed_out {
            entries.push((display, -1.0, true));
        } else {
            entries.push((display, round2(total as f64 / GB), false));
        }
    }

    entries.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    entries
        .into_iter()
        .take(top_n)
        .map(|(path, size_gb, timed_out)| {
            if timed_out {
                json!({"path": path, "size_gb": -1, "note": "scan_timeout"})
            } else {
                json!({"path": path, "size_gb": size_gb})
            }
        })
        .collect()
}

// ── Large + stale files (single walk) ────────────────────────────────────────

fn scan_files(home: &Path, min_mb: u64, stale_days: i64, top_n: usize) -> (Vec<Value>, Vec<Value>) {
    let cutoff = SystemTime::now()
        .checked_sub(Duration::from_secs((stale_days as u64) * 86400))
        .unwrap_or(SystemTime::UNIX_EPOCH);
    let started = Instant::now();
    let min_bytes = min_mb * 1024 * 1024;

    let mut large: Vec<(String, f64, String)> = Vec::new();
    let mut stale: Vec<(String, f64, String)> = Vec::new();

    let walker = WalkDir::new(home).follow_links(false).into_iter().filter_entry(|e| {
        let name = e.file_name().to_string_lossy();
        !EXCLUDES.iter().any(|x| name == *x)
    });

    for entry in walker.filter_map(|e| e.ok()) {
        if started.elapsed() > SCAN_BUDGET {
            break;
        }
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        if !meta.is_file() {
            continue;
        }
        if meta.len() < min_bytes {
            continue;
        }
        let path = entry.path();
        let rel = path
            .strip_prefix(home)
            .map(|r| format!("~/{}", r.display()))
            .unwrap_or_else(|_| path.display().to_string());
        let size_mb = round1(meta.len() as f64 / MB);
        let modified = meta
            .modified()
            .ok()
            .map(format_date)
            .unwrap_or_else(|| "unknown".to_string());
        let accessed = meta
            .accessed()
            .ok()
            .unwrap_or(SystemTime::UNIX_EPOCH);

        large.push((rel.clone(), size_mb, modified));
        if accessed < cutoff {
            let acc_str = format_date(accessed);
            stale.push((rel, size_mb, acc_str));
        }
    }

    large.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    stale.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    let large_out: Vec<Value> = large
        .into_iter()
        .take(top_n)
        .map(|(path, size_mb, modified)| json!({"path": path, "size_mb": size_mb, "modified": modified}))
        .collect();
    let stale_out: Vec<Value> = stale
        .into_iter()
        .take(top_n)
        .map(|(path, size_mb, accessed)| {
            json!({"path": path, "size_mb": size_mb, "last_accessed": accessed})
        })
        .collect();

    (large_out, stale_out)
}

// ── Caches ───────────────────────────────────────────────────────────────────

fn scan_caches(home: &Path) -> Vec<Value> {
    let candidates: Vec<PathBuf> = vec![
        home.join("Library").join("Caches"),
        home.join("Library").join("Logs"),
        home.join(".npm").join("_cacache"),
        home.join(".cache"),
    ];
    let mut out: Vec<(String, f64)> = Vec::new();
    for d in &candidates {
        if d.is_dir() {
            let size_gb = round2(dir_size(d) as f64 / GB);
            let display = display_path(d, home);
            out.push((display, size_gb));
        }
    }
    // Homebrew cache via `brew --cache`
    if let Some(brew) = run_str("brew", &["--cache"]) {
        let brew = brew.trim().to_string();
        if !brew.is_empty() {
            let p = PathBuf::from(&brew);
            if p.is_dir() {
                out.push((brew, round2(dir_size(&p) as f64 / GB)));
            }
        }
    }
    // Trash
    let trash = home.join(".Trash");
    if trash.is_dir() {
        out.push(("~/.Trash".to_string(), round2(dir_size(&trash) as f64 / GB)));
    }
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    out.into_iter()
        .map(|(path, size_gb)| json!({"path": path, "size_gb": size_gb}))
        .collect()
}

fn dir_size(p: &Path) -> u64 {
    let started = Instant::now();
    let mut total: u64 = 0;
    for entry in WalkDir::new(p).follow_links(false).into_iter().filter_map(|e| e.ok()) {
        if started.elapsed() > PER_DIR_BUDGET {
            break;
        }
        if let Ok(meta) = entry.metadata() {
            if meta.is_file() {
                total = total.saturating_add(meta.len());
            }
        }
    }
    total
}

fn display_path(p: &Path, home: &Path) -> String {
    if let Ok(rel) = p.strip_prefix(home) {
        format!("~/{}", rel.display())
    } else {
        p.display().to_string()
    }
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn run_str(cmd: &str, args: &[&str]) -> Option<String> {
    std::process::Command::new(cmd)
        .args(args)
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
}

fn format_date(t: SystemTime) -> String {
    let dt: chrono::DateTime<chrono::Local> = t.into();
    dt.format("%Y-%m-%d").to_string()
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}
