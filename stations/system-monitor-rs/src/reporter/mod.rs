//! LLM-driven weekly/monthly reports (Phase 4).
//!
//! `run(cfg, kind)` reads the last 7 (weekly) or 30 (monthly) days of
//! `snapshot-*.json` from `~/.claude/data/system-monitor/`, aggregates trend
//! stats, asks the LLM router for commentary, then writes Markdown to
//! `reports/{kind}-{YYYY-MM-DD}.md`.

pub mod llm_router;
pub mod markdown;

use anyhow::{Context, Result};
use chrono::{DateTime, Duration, NaiveDateTime, TimeZone, Utc};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use crate::config::Settings;

const SNAPSHOT_PREFIX: &str = "snapshot-";
const SNAPSHOT_SUFFIX: &str = ".json";
const FILENAME_TS_FMT: &str = "%Y-%m-%d_%H%M%S";

pub async fn run(cfg: &Settings, kind: &str) -> Result<()> {
    let kind = match kind {
        "weekly" | "monthly" => kind,
        other => {
            tracing::warn!(kind=%other, "unknown report kind, defaulting to weekly");
            "weekly"
        }
    };
    let window_days: u32 = if kind == "monthly" { 30 } else { 7 };

    crate::shared::paths::ensure_dirs(cfg).ok();

    let snapshots = load_recent_snapshots(cfg, window_days)
        .context("failed to load snapshots for report")?;
    tracing::info!(
        kind = kind,
        window_days,
        count = snapshots.len(),
        "reporter loaded snapshots"
    );

    let stats = markdown::summarize_snapshots(&snapshots, window_days);

    let prompt = build_prompt(kind, &stats);
    let (llm_text, engine) = match llm_router::generate(cfg, &prompt).await {
        Ok(pair) => pair,
        Err(e) => {
            tracing::warn!(error=%e, "llm router errored, writing offline report");
            (None, "offline")
        }
    };

    let today = Utc::now().format("%Y-%m-%d").to_string();
    let mut body = markdown::render(&stats, llm_text.as_deref(), kind, &today);
    body.push_str(&format!(
        "\n---\n_engine={} kind={} generated_at={}_\n",
        engine,
        kind,
        Utc::now().format("%Y-%m-%dT%H:%M:%SZ")
    ));

    let out_path = crate::shared::paths::report_path(cfg, kind, &today);
    std::fs::write(&out_path, body)
        .with_context(|| format!("failed to write report {}", out_path.display()))?;
    tracing::info!(path=%out_path.display(), engine=%engine, "reporter wrote report");

    Ok(())
}

fn build_prompt(kind: &str, stats: &markdown::SummaryStats) -> String {
    let header = if kind == "monthly" {
        "You are a senior macOS sysadmin assistant. Write a concise MONTHLY system report in Markdown."
    } else {
        "You are a macOS sysadmin assistant. Write a concise WEEKLY system report in Markdown."
    };
    format!(
        "{header}\n\nReport on these aggregated stats (window={} days, {} snapshots).\n\
        Focus on trends, anomalies, and actionable suggestions. Keep it under 400 words.\n\n\
        STATS:\n{}",
        stats.window_days,
        stats.snapshot_count,
        markdown::build_prompt_digest(stats)
    )
}

/// Read all snapshot-*.json files within the last `days` days.
fn load_recent_snapshots(cfg: &Settings, days: u32) -> Result<Vec<Value>> {
    let dir = crate::shared::paths::snapshots_dir(cfg);
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let cutoff = Utc::now() - Duration::days(days as i64);

    let mut paths: Vec<(DateTime<Utc>, PathBuf)> = Vec::new();
    for entry in std::fs::read_dir(&dir)? {
        let entry = match entry {
            Ok(e) => e,
            Err(e) => {
                tracing::debug!(error=%e, "skip dir entry");
                continue;
            }
        };
        let path = entry.path();
        let Some(stem) = path.file_name().and_then(|s| s.to_str()) else {
            continue;
        };
        if !stem.starts_with(SNAPSHOT_PREFIX) || !stem.ends_with(SNAPSHOT_SUFFIX) {
            continue;
        }
        let ts_part = &stem[SNAPSHOT_PREFIX.len()..stem.len() - SNAPSHOT_SUFFIX.len()];
        let Some(ts) = parse_filename_ts(ts_part) else {
            continue;
        };
        if ts >= cutoff {
            paths.push((ts, path));
        }
    }
    paths.sort_by_key(|(ts, _)| *ts);

    let mut out = Vec::with_capacity(paths.len());
    for (_, path) in paths {
        match read_json(&path) {
            Ok(v) => out.push(v),
            Err(e) => tracing::warn!(path=%path.display(), error=%e, "skip unreadable snapshot"),
        }
    }
    Ok(out)
}

fn parse_filename_ts(s: &str) -> Option<DateTime<Utc>> {
    NaiveDateTime::parse_from_str(s, FILENAME_TS_FMT)
        .ok()
        .map(|naive| Utc.from_utc_datetime(&naive))
}

fn read_json(path: &Path) -> Result<Value> {
    let body = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str(&body)?)
}

// ---------------------------------------------------------------------------
// /reports endpoint helpers (signatures unchanged from Phase 0).
// ---------------------------------------------------------------------------

pub fn list(cfg: &Settings) -> Result<Value> {
    let dir = crate::shared::paths::reports_dir(cfg);
    if !dir.exists() {
        return Ok(json!([]));
    }
    let mut items = Vec::new();
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        if entry.path().extension().and_then(|s| s.to_str()) == Some("md") {
            let name = entry.file_name().to_string_lossy().to_string();
            let meta = entry.metadata()?;
            items.push(json!({
                "filename": name,
                "size_bytes": meta.len(),
            }));
        }
    }
    Ok(json!(items))
}

pub fn get(cfg: &Settings, filename: &str) -> Result<Value> {
    let dir = crate::shared::paths::reports_dir(cfg);
    let path = dir.join(filename);
    // Refuse path traversal.
    if !path.starts_with(&dir) {
        anyhow::bail!("invalid filename");
    }
    let body = std::fs::read_to_string(path)?;
    Ok(json!({ "filename": filename, "content": body }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_ts_known_format() {
        let ts = parse_filename_ts("2026-03-03_032941").unwrap();
        assert_eq!(ts.format("%Y-%m-%d %H:%M:%S").to_string(), "2026-03-03 03:29:41");
    }

    #[test]
    fn parse_ts_invalid() {
        assert!(parse_filename_ts("nope").is_none());
    }
}
