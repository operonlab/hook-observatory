//! macOS system metrics collection (CPU/Memory/Network/Disk/Claude procs).
//!
//! Mirrors `agent_metrics.sysmon_collector` 1:1: same subprocess calls
//! (`sysctl`, `vm_stat`, `netstat`, `diskutil`, `ps`) so output values match
//! Python byte-for-byte.

use anyhow::Result;
use chrono::Utc;
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::process::Command;

const IDLE_CPU: f64 = 1.0;
const NETWORK_RATE_MAX_DT: f64 = 30.0;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SysmonSnapshot {
    pub ts: String,

    pub cpu_pct: f64,
    pub cpu_display: String,

    pub mem_used_gb: f64,
    pub mem_total_gb: f64,
    pub mem_pct: f64,
    pub mem_pressure: i64,
    pub mem_display: String,

    pub net_rx_bps: i64,
    pub net_tx_bps: i64,
    pub net_display: String,

    pub disk_used_gb: f64,
    pub disk_total_gb: f64,
    pub disk_pct: f64,
    pub disk_display: String,

    pub cc_active: i64,
    pub cc_idle: i64,
    pub cc_mem_mb: f64,
    pub cc_display: String,

    // Quota slots filled by Phase 3 collector
    #[serde(default = "qmark")]
    pub llm_cc_5h: String,
    #[serde(default = "qmark")]
    pub llm_cc_7d: String,
    #[serde(default = "qmark")]
    pub llm_cc_ex: String,
    #[serde(default = "qmark")]
    pub llm_cx_5h: String,
    #[serde(default = "qmark")]
    pub llm_cx_7d: String,
    #[serde(default = "qmark")]
    pub llm_gm_pro: String,
    #[serde(default = "qmark")]
    pub llm_display: String,
}

fn qmark() -> String {
    "?".to_string()
}

impl Default for SysmonSnapshot {
    fn default() -> Self {
        Self {
            ts: String::new(),
            cpu_pct: 0.0,
            cpu_display: "?%".into(),
            mem_used_gb: 0.0,
            mem_total_gb: 0.0,
            mem_pct: 0.0,
            mem_pressure: 99,
            mem_display: "?/?G ?%".into(),
            net_rx_bps: 0,
            net_tx_bps: 0,
            net_display: "↓-- ↑--".into(),
            disk_used_gb: 0.0,
            disk_total_gb: 0.0,
            disk_pct: 0.0,
            disk_display: "?/?G ?%".into(),
            cc_active: 0,
            cc_idle: 0,
            cc_mem_mb: 0.0,
            cc_display: "0".into(),
            llm_cc_5h: qmark(),
            llm_cc_7d: qmark(),
            llm_cc_ex: qmark(),
            llm_cx_5h: qmark(),
            llm_cx_7d: qmark(),
            llm_gm_pro: qmark(),
            llm_display: qmark(),
        }
    }
}

// Shared state for network rate calculation
static PREV_NET: Lazy<Mutex<(i64, i64, f64)>> = Lazy::new(|| Mutex::new((0, 0, 0.0)));

// Disk cache (60s TTL)
static DISK_CACHE: Lazy<Mutex<Option<(f64, DiskInfo)>>> = Lazy::new(|| Mutex::new(None));
const DISK_CACHE_TTL: f64 = 60.0;

#[derive(Debug, Clone)]
pub struct DiskInfo {
    pub used_gb: f64,
    pub total_gb: f64,
    pub pct: f64,
    pub display: String,
}

async fn run(cmd: &str, args: &[&str]) -> Result<String> {
    let out = Command::new(cmd).args(args).output().await?;
    if !out.status.success() {
        anyhow::bail!(
            "{cmd} {args:?} exited {:?}: {}",
            out.status,
            String::from_utf8_lossy(&out.stderr).trim()
        );
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

// ── CPU ─────────────────────────────────────────────────────────

pub async fn collect_cpu() -> (f64, String) {
    async fn inner() -> Result<(f64, String)> {
        let load_raw = run("sysctl", &["-n", "vm.loadavg"]).await?;
        // Output like: "{ 1.50 1.20 0.90 }"
        let trimmed = load_raw.trim();
        let parts: Vec<&str> = trimmed.split_whitespace().collect();
        let load: f64 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0.0);

        let ncpu_raw = run("sysctl", &["-n", "hw.ncpu"]).await?;
        let ncpu: i64 = ncpu_raw.trim().parse().unwrap_or(1);

        let pct = (load / ncpu as f64 * 100.0).min(100.0);
        Ok((round1(pct), format!("{:.0}%", pct)))
    }
    inner().await.unwrap_or((0.0, "?%".into()))
}

// ── Memory ──────────────────────────────────────────────────────

fn parse_vm_stat(output: &str, label: &str) -> i64 {
    for line in output.lines() {
        if line.contains(label) {
            let parts: Vec<&str> = line.splitn(2, ':').collect();
            if parts.len() == 2 {
                let num = parts[1].trim().trim_end_matches('.');
                if let Ok(n) = num.parse() {
                    return n;
                }
            }
        }
    }
    0
}

#[derive(Debug, Clone)]
pub struct MemoryReading {
    pub used_gb: f64,
    pub total_gb: f64,
    pub pct: f64,
    pub pressure: i64,
    pub display: String,
}

pub async fn collect_memory() -> MemoryReading {
    async fn inner() -> Result<MemoryReading> {
        let total_bytes: i64 = run("sysctl", &["-n", "hw.memsize"])
            .await?
            .trim()
            .parse()
            .unwrap_or(0);
        let total_gb = total_bytes as f64 / 1024_f64.powi(3);

        let page_size: i64 = run("sysctl", &["-n", "hw.pagesize"])
            .await?
            .trim()
            .parse()
            .unwrap_or(4096);

        let vm_output = run("vm_stat", &[]).await?;
        let active = parse_vm_stat(&vm_output, "Pages active");
        let wired = parse_vm_stat(&vm_output, "Pages wired");
        let compressed = parse_vm_stat(&vm_output, "Pages occupied by compressor");

        let used_pages = active + wired + compressed;
        let used_bytes = used_pages * page_size;
        let used_gb = used_bytes as f64 / 1024_f64.powi(3);
        let pct = if total_bytes > 0 {
            used_bytes as f64 * 100.0 / total_bytes as f64
        } else {
            0.0
        };

        let pressure: i64 = run("sysctl", &["-n", "kern.memorystatus_level"])
            .await
            .ok()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(99);

        let indicator = if pressure < 10 {
            " ✖"
        } else if pressure < 20 {
            " ⚠"
        } else {
            ""
        };

        let display = format!(
            "{:.1}/{:.0}G {:.0}%{}",
            used_gb, total_gb, pct, indicator
        );

        Ok(MemoryReading {
            used_gb: round1(used_gb),
            total_gb: round0(total_gb),
            pct: round1(pct),
            pressure,
            display,
        })
    }
    inner().await.unwrap_or(MemoryReading {
        used_gb: 0.0,
        total_gb: 0.0,
        pct: 0.0,
        pressure: 99,
        display: "?/?G ?%".into(),
    })
}

// ── Network ─────────────────────────────────────────────────────

fn format_speed(bps: i64) -> String {
    if bps >= 1_048_576 {
        format!("{:.1}M/s", bps as f64 / 1_048_576.0)
    } else if bps >= 1024 {
        format!("{:.0}K/s", bps as f64 / 1024.0)
    } else {
        format!("{}B/s", bps)
    }
}

#[derive(Debug, Clone)]
pub struct NetworkReading {
    pub rx_bps: i64,
    pub tx_bps: i64,
    pub display: String,
}

pub async fn collect_network() -> NetworkReading {
    async fn inner() -> Result<NetworkReading> {
        let route = run("route", &["-n", "get", "default"]).await?;
        let mut iface = "";
        for line in route.lines() {
            if line.contains("interface:") {
                iface = line.split_whitespace().last().unwrap_or("");
                break;
            }
        }
        if iface.is_empty() {
            return Ok(NetworkReading {
                rx_bps: 0,
                tx_bps: 0,
                display: "↓-- ↑--".into(),
            });
        }

        let netstat_out = run("netstat", &["-ib", "-I", iface]).await?;

        let mut rx_now = 0_i64;
        let mut tx_now = 0_i64;
        for line in netstat_out.lines() {
            if line.contains("Link") {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 10 {
                    rx_now = parts[6].parse().unwrap_or(0);
                    tx_now = parts[9].parse().unwrap_or(0);
                }
                break;
            }
        }

        let ts_now = now_secs();
        let (rx_rate, tx_rate) = {
            let mut prev = PREV_NET.lock().unwrap();
            let (prev_rx, prev_tx, prev_ts) = *prev;
            let result = if prev_ts > 0.0 {
                let dt = ts_now - prev_ts;
                if dt > 0.0 && dt < NETWORK_RATE_MAX_DT {
                    (
                        ((rx_now - prev_rx) as f64 / dt).max(0.0) as i64,
                        ((tx_now - prev_tx) as f64 / dt).max(0.0) as i64,
                    )
                } else {
                    (0, 0)
                }
            } else {
                (0, 0)
            };
            *prev = (rx_now, tx_now, ts_now);
            result
        };

        let display = format!("↓{} ↑{}", format_speed(rx_rate), format_speed(tx_rate));
        Ok(NetworkReading {
            rx_bps: rx_rate,
            tx_bps: tx_rate,
            display,
        })
    }
    inner().await.unwrap_or(NetworkReading {
        rx_bps: 0,
        tx_bps: 0,
        display: "↓-- ↑--".into(),
    })
}

// ── Disk ────────────────────────────────────────────────────────

fn extract_bytes(line: &str) -> i64 {
    // matches `(\d+)\s*B(?:ytes)?` from Python
    // Skip past digits, then optional whitespace, then 'B'.
    // Simplified: scan for "( <digits> Bytes)" pattern.
    let chars: Vec<char> = line.chars().collect();
    let mut best: i64 = 0;
    let mut i = 0;
    while i < chars.len() {
        if chars[i].is_ascii_digit() {
            let start = i;
            while i < chars.len() && chars[i].is_ascii_digit() {
                i += 1;
            }
            // skip whitespace
            let mut j = i;
            while j < chars.len() && chars[j].is_whitespace() {
                j += 1;
            }
            if j < chars.len() && chars[j] == 'B' {
                if let Ok(n) = chars[start..i].iter().collect::<String>().parse::<i64>() {
                    best = n;
                    return best;
                }
            }
            continue;
        }
        i += 1;
    }
    best
}

async fn collect_apfs() -> Result<DiskInfo> {
    let output = run("diskutil", &["apfs", "list"]).await?;

    let mut total_bytes: i64 = 0;
    let mut free_bytes: i64 = 0;
    for line in output.lines() {
        if line.contains("Size (Capacity Ceiling)") && total_bytes == 0 {
            total_bytes = extract_bytes(line);
        } else if line.contains("Capacity Not Allocated") && free_bytes == 0 {
            free_bytes = extract_bytes(line);
        }
    }
    if total_bytes <= 0 {
        return collect_df_fallback().await;
    }
    let used_bytes = total_bytes - free_bytes;
    let total_gb = total_bytes as f64 / 1024_f64.powi(3);
    let used_gb = used_bytes as f64 / 1024_f64.powi(3);
    let pct = used_bytes as f64 * 100.0 / total_bytes as f64;

    Ok(DiskInfo {
        used_gb: round1(used_gb),
        total_gb: round1(total_gb),
        pct: round1(pct),
        display: format!("{}/{}G {:.0}%", used_gb as i64, total_gb as i64, pct),
    })
}

async fn collect_df_fallback() -> Result<DiskInfo> {
    let out = run("df", &["-g", "/"]).await?;
    let lines: Vec<&str> = out.trim().lines().collect();
    if lines.len() >= 2 {
        let parts: Vec<&str> = lines[1].split_whitespace().collect();
        let total_gb: f64 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0.0);
        let used_gb: f64 = parts.get(2).and_then(|s| s.parse().ok()).unwrap_or(0.0);
        let pct = if total_gb > 0.0 { used_gb / total_gb * 100.0 } else { 0.0 };
        return Ok(DiskInfo {
            used_gb,
            total_gb,
            pct: round1(pct),
            display: format!("{}/{}G {:.0}%", used_gb as i64, total_gb as i64, pct),
        });
    }
    Ok(DiskInfo {
        used_gb: 0.0,
        total_gb: 0.0,
        pct: 0.0,
        display: "?/?G ?%".into(),
    })
}

pub async fn collect_disk() -> DiskInfo {
    let now = now_secs();
    {
        let cache = DISK_CACHE.lock().unwrap();
        if let Some((ts, ref info)) = *cache {
            if now - ts < DISK_CACHE_TTL {
                return info.clone();
            }
        }
    }
    let info = match collect_apfs().await {
        Ok(i) => i,
        Err(_) => collect_df_fallback().await.unwrap_or(DiskInfo {
            used_gb: 0.0,
            total_gb: 0.0,
            pct: 0.0,
            display: "?/?G ?%".into(),
        }),
    };
    {
        let mut cache = DISK_CACHE.lock().unwrap();
        *cache = Some((now, info.clone()));
    }
    info
}

// ── Claude Code processes ───────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ClaudeProcs {
    pub active: i64,
    pub idle: i64,
    pub mem_mb: f64,
    pub display: String,
}

pub async fn collect_claude_procs() -> ClaudeProcs {
    async fn inner() -> Result<ClaudeProcs> {
        let output = run("ps", &["-eo", "pid=,rss=,%cpu=,comm="]).await?;
        let mut active_n = 0_i64;
        let mut active_kb = 0_i64;
        let mut idle_n = 0_i64;
        let mut idle_kb = 0_i64;

        for line in output.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() < 4 {
                continue;
            }
            if parts[3] != "claude" {
                continue;
            }
            let rss_kb: i64 = parts[1].parse().unwrap_or(0);
            let cpu: f64 = parts[2].parse().unwrap_or(0.0);
            if cpu < IDLE_CPU {
                idle_n += 1;
                idle_kb += rss_kb;
            } else {
                active_n += 1;
                active_kb += rss_kb;
            }
        }

        let total = active_n + idle_n;
        let total_mb = (active_kb + idle_kb) as f64 / 1024.0;
        if total == 0 {
            return Ok(ClaudeProcs {
                active: 0,
                idle: 0,
                mem_mb: 0.0,
                display: "0".into(),
            });
        }
        let mut parts_display: Vec<String> = vec![];
        if active_n > 0 {
            let active_gb = active_kb as f64 / (1024.0 * 1024.0);
            parts_display.push(format!("{}>{:.1}G", active_n, active_gb));
        }
        if idle_n > 0 {
            let idle_gb = idle_kb as f64 / (1024.0 * 1024.0);
            parts_display.push(format!("{}*{:.1}G", idle_n, idle_gb));
        }
        Ok(ClaudeProcs {
            active: active_n,
            idle: idle_n,
            mem_mb: round1(total_mb),
            display: parts_display.join(" "),
        })
    }
    inner().await.unwrap_or(ClaudeProcs {
        active: 0,
        idle: 0,
        mem_mb: 0.0,
        display: "?".into(),
    })
}

// ── collect_all ─────────────────────────────────────────────────

pub async fn collect_all() -> SysmonSnapshot {
    let (cpu_pct, cpu_display) = collect_cpu().await;
    let mem = collect_memory().await;
    let net = collect_network().await;
    let disk = collect_disk().await;
    let cc = collect_claude_procs().await;

    SysmonSnapshot {
        ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false),
        cpu_pct,
        cpu_display,
        mem_used_gb: mem.used_gb,
        mem_total_gb: mem.total_gb,
        mem_pct: mem.pct,
        mem_pressure: mem.pressure,
        mem_display: mem.display,
        net_rx_bps: net.rx_bps,
        net_tx_bps: net.tx_bps,
        net_display: net.display,
        disk_used_gb: disk.used_gb,
        disk_total_gb: disk.total_gb,
        disk_pct: disk.pct,
        disk_display: disk.display,
        cc_active: cc.active,
        cc_idle: cc.idle,
        cc_mem_mb: cc.mem_mb,
        cc_display: cc.display,
        ..Default::default()
    }
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

/// Python `round(v, n)` uses banker's rounding (round-half-to-even),
/// while Rust's `f64::round` is round-half-away-from-zero. The two
/// disagree at exact .5 boundaries (e.g. 2.5 → Python 2, Rust 3).
/// To preserve byte-for-byte parity with the Python sysmon snapshots
/// already on disk, replicate banker's rounding here.
fn round1(v: f64) -> f64 {
    banker_round(v * 10.0) / 10.0
}

fn round0(v: f64) -> f64 {
    banker_round(v)
}

fn banker_round(v: f64) -> f64 {
    let floor = v.floor();
    let frac = v - floor;
    if frac < 0.5 {
        floor
    } else if frac > 0.5 {
        floor + 1.0
    } else {
        // Exactly half — round to even
        if (floor as i64) % 2 == 0 {
            floor
        } else {
            floor + 1.0
        }
    }
}

#[cfg(test)]
mod sysmon_round_tests {
    use super::banker_round;

    #[test]
    fn banker_round_matches_python_at_halves() {
        assert_eq!(banker_round(0.5), 0.0);
        assert_eq!(banker_round(1.5), 2.0);
        assert_eq!(banker_round(2.5), 2.0);
        assert_eq!(banker_round(3.5), 4.0);
        assert_eq!(banker_round(-0.5), 0.0);
        assert_eq!(banker_round(-1.5), -2.0);
    }

    #[test]
    fn banker_round_unaffected_for_non_halves() {
        assert_eq!(banker_round(1.4), 1.0);
        assert_eq!(banker_round(1.6), 2.0);
        assert_eq!(banker_round(2.4), 2.0);
        assert_eq!(banker_round(2.6), 3.0);
    }
}

#[allow(dead_code)]
fn duration_since(epoch: SystemTime) -> Duration {
    SystemTime::now().duration_since(epoch).unwrap_or_default()
}
