//! Snapshot aggregation + Markdown rendering for weekly/monthly reports.
//!
//! Phase 4 worker: aggregates ~7 day (weekly) / ~30 day (monthly) snapshots
//! from `~/.claude/data/system-monitor/snapshot-*.json` into trend stats and
//! a Markdown body. The LLM section is filled in by `llm_router`.

use serde_json::Value;
use std::collections::HashMap;

/// Aggregated stats across all snapshots in the window.
#[derive(Debug, Clone, Default)]
pub struct SummaryStats {
    pub snapshot_count: usize,
    pub window_days: u32,
    pub first_ts: Option<String>,
    pub last_ts: Option<String>,

    pub cpu: MetricStats,
    pub mem: MetricStats,
    pub disk: MetricStats,
    pub swap_used_gb: MetricStats,

    /// pressure_level (top-level) frequency: normal/warning/critical/...
    pub pressure_counts: HashMap<String, usize>,

    /// Process name → number of snapshots it appeared in (top 5 retained).
    pub top_processes: Vec<(String, usize)>,
}

#[derive(Debug, Clone, Default)]
pub struct MetricStats {
    pub samples: usize,
    pub mean: f64,
    pub min: f64,
    pub max: f64,
}

impl MetricStats {
    fn from_values(values: &[f64]) -> Self {
        if values.is_empty() {
            return Self::default();
        }
        let samples = values.len();
        let sum: f64 = values.iter().sum();
        let mean = sum / samples as f64;
        let min = values.iter().cloned().fold(f64::INFINITY, f64::min);
        let max = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        Self { samples, mean, min, max }
    }

    fn fmt_pct(&self) -> String {
        if self.samples == 0 {
            "n/a".to_string()
        } else {
            format!(
                "mean {:.1}% / min {:.1}% / max {:.1}% (n={})",
                self.mean, self.min, self.max, self.samples
            )
        }
    }

    fn fmt_gb(&self) -> String {
        if self.samples == 0 {
            "n/a".to_string()
        } else {
            format!(
                "mean {:.2} GB / min {:.2} GB / max {:.2} GB (n={})",
                self.mean, self.min, self.max, self.samples
            )
        }
    }
}

/// Compute trend stats from a slice of snapshot JSON values.
pub fn summarize_snapshots(snapshots: &[Value], window_days: u32) -> SummaryStats {
    let mut cpu = Vec::with_capacity(snapshots.len());
    let mut mem = Vec::with_capacity(snapshots.len());
    let mut disk = Vec::with_capacity(snapshots.len());
    let mut swap = Vec::with_capacity(snapshots.len());
    let mut pressure_counts: HashMap<String, usize> = HashMap::new();
    let mut process_counts: HashMap<String, usize> = HashMap::new();
    let mut first_ts: Option<String> = None;
    let mut last_ts: Option<String> = None;

    for snap in snapshots {
        if let Some(ts) = snap.get("timestamp").and_then(|v| v.as_str()) {
            if first_ts.is_none() {
                first_ts = Some(ts.to_string());
            }
            last_ts = Some(ts.to_string());
        }

        if let Some(v) = snap
            .get("hardware")
            .and_then(|h| h.get("cpu"))
            .and_then(|c| c.get("usage_pct"))
            .and_then(|x| x.as_f64())
        {
            cpu.push(v);
        }
        if let Some(v) = snap
            .get("hardware")
            .and_then(|h| h.get("memory"))
            .and_then(|m| m.get("usage_pct"))
            .and_then(|x| x.as_f64())
        {
            mem.push(v);
        }
        if let Some(v) = snap
            .get("disk")
            .and_then(|d| d.get("usage_pct"))
            .and_then(|x| x.as_f64())
        {
            disk.push(v);
        }
        if let Some(v) = snap
            .get("hardware")
            .and_then(|h| h.get("swap"))
            .and_then(|s| s.get("used_gb"))
            .and_then(|x| x.as_f64())
        {
            swap.push(v);
        }

        if let Some(level) = snap.get("pressure_level").and_then(|v| v.as_str()) {
            *pressure_counts.entry(level.to_string()).or_insert(0) += 1;
        }

        if let Some(procs) = snap.get("top_processes").and_then(|v| v.as_array()) {
            for p in procs {
                if let Some(name) = p.get("name").and_then(|v| v.as_str()) {
                    *process_counts.entry(name.to_string()).or_insert(0) += 1;
                }
            }
        }
    }

    let mut top: Vec<(String, usize)> = process_counts.into_iter().collect();
    top.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    top.truncate(5);

    SummaryStats {
        snapshot_count: snapshots.len(),
        window_days,
        first_ts,
        last_ts,
        cpu: MetricStats::from_values(&cpu),
        mem: MetricStats::from_values(&mem),
        disk: MetricStats::from_values(&disk),
        swap_used_gb: MetricStats::from_values(&swap),
        pressure_counts,
        top_processes: top,
    }
}

/// Compact JSON-ish digest used as the LLM prompt payload (token-friendly).
pub fn build_prompt_digest(stats: &SummaryStats) -> String {
    let mut s = String::new();
    s.push_str(&format!(
        "window_days={} snapshots={} first={} last={}\n",
        stats.window_days,
        stats.snapshot_count,
        stats.first_ts.as_deref().unwrap_or("?"),
        stats.last_ts.as_deref().unwrap_or("?"),
    ));
    s.push_str(&format!("cpu_usage_pct: {}\n", stats.cpu.fmt_pct()));
    s.push_str(&format!("mem_usage_pct: {}\n", stats.mem.fmt_pct()));
    s.push_str(&format!("disk_usage_pct: {}\n", stats.disk.fmt_pct()));
    s.push_str(&format!("swap_used: {}\n", stats.swap_used_gb.fmt_gb()));

    s.push_str("pressure_level_counts:\n");
    let mut levels: Vec<(&String, &usize)> = stats.pressure_counts.iter().collect();
    levels.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in levels {
        s.push_str(&format!("  - {}: {}\n", k, v));
    }

    s.push_str("top_processes_by_appearance:\n");
    for (name, count) in &stats.top_processes {
        s.push_str(&format!("  - {} (appearances={})\n", name, count));
    }
    s
}

/// Render the final Markdown report. `llm_text` is None when all LLM
/// providers failed; the caller already logged the fallback path.
pub fn render(stats: &SummaryStats, llm_text: Option<&str>, kind: &str, date: &str) -> String {
    let title_kind = match kind {
        "weekly" => "Weekly",
        "monthly" => "Monthly",
        other => other,
    };

    let mut out = String::new();
    out.push_str(&format!(
        "# Workshop {} Report — {}\n\n",
        title_kind, date
    ));

    // System Health
    out.push_str("## System Health\n\n");
    out.push_str(&format!(
        "- Window: last {} days ({} snapshots)\n",
        stats.window_days, stats.snapshot_count
    ));
    if let (Some(first), Some(last)) = (&stats.first_ts, &stats.last_ts) {
        out.push_str(&format!("- Range: {} → {}\n", first, last));
    }
    out.push_str(&format!("- CPU usage: {}\n", stats.cpu.fmt_pct()));
    out.push_str(&format!("- Memory usage: {}\n", stats.mem.fmt_pct()));
    out.push_str(&format!("- Disk usage: {}\n", stats.disk.fmt_pct()));
    out.push_str(&format!("- Swap used: {}\n", stats.swap_used_gb.fmt_gb()));
    out.push('\n');

    // Alerts
    out.push_str("## Alerts\n\n");
    if stats.pressure_counts.is_empty() {
        out.push_str("- (no pressure_level data)\n");
    } else {
        let mut levels: Vec<(&String, &usize)> = stats.pressure_counts.iter().collect();
        levels.sort_by(|a, b| b.1.cmp(a.1));
        for (level, count) in levels {
            out.push_str(&format!("- {}: {}\n", level, count));
        }
    }
    out.push('\n');

    // Top Processes
    out.push_str("## Top Processes\n\n");
    if stats.top_processes.is_empty() {
        out.push_str("- (no process samples)\n");
    } else {
        for (name, count) in &stats.top_processes {
            out.push_str(&format!("- {} (appeared in {} snapshots)\n", name, count));
        }
    }
    out.push('\n');

    // LLM Insights
    out.push_str("## LLM Insights\n\n");
    match llm_text {
        Some(text) if !text.trim().is_empty() => {
            out.push_str(text.trim_end());
            out.push('\n');
        }
        _ => {
            out.push_str("_LLM unavailable — fallback report (raw stats only)._\n");
        }
    }
    out.push('\n');

    // Raw Stats
    out.push_str("## Raw Stats\n\n");
    out.push_str("```\n");
    out.push_str(&build_prompt_digest(stats));
    out.push_str("```\n");

    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn snap(cpu: f64, mem: f64, disk: f64, swap: f64, pressure: &str, proc_name: &str) -> Value {
        json!({
            "timestamp": "2026-03-03T03:29:41.555541+00:00",
            "hardware": {
                "cpu": {"usage_pct": cpu},
                "memory": {"usage_pct": mem},
                "swap": {"used_gb": swap},
            },
            "disk": {"usage_pct": disk},
            "pressure_level": pressure,
            "top_processes": [{"name": proc_name}],
        })
    }

    #[test]
    fn summarize_basic() {
        let snaps = vec![
            snap(10.0, 50.0, 40.0, 1.0, "normal", "npm"),
            snap(30.0, 60.0, 41.0, 2.0, "critical", "npm"),
        ];
        let s = summarize_snapshots(&snaps, 7);
        assert_eq!(s.snapshot_count, 2);
        assert!((s.cpu.mean - 20.0).abs() < 1e-6);
        assert_eq!(s.cpu.min, 10.0);
        assert_eq!(s.cpu.max, 30.0);
        assert_eq!(s.pressure_counts["critical"], 1);
        assert_eq!(s.top_processes[0].0, "npm");
        assert_eq!(s.top_processes[0].1, 2);
    }

    #[test]
    fn render_includes_sections() {
        let stats = summarize_snapshots(
            &[snap(10.0, 50.0, 40.0, 1.0, "normal", "npm")],
            7,
        );
        let md = render(&stats, Some("looks fine"), "weekly", "2026-03-03");
        assert!(md.contains("# Workshop Weekly Report"));
        assert!(md.contains("## System Health"));
        assert!(md.contains("## Alerts"));
        assert!(md.contains("## Top Processes"));
        assert!(md.contains("## LLM Insights"));
        assert!(md.contains("looks fine"));
        assert!(md.contains("## Raw Stats"));
    }
}
