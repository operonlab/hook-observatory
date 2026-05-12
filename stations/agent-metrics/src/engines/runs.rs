//! MaestroRun persistence — SQLite `dispatch_runs` table.

use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::SqlitePool;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MaestroRun {
    pub id: String,
    pub name: String,
    pub pattern: String,
    pub task: String,
    pub budget: String,
    pub cwd: String,
    #[serde(default = "default_tier")]
    pub tier: String,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub phases: Vec<Value>,
    #[serde(default)]
    pub results: Vec<Value>,
    #[serde(default)]
    pub started_at: String,
    #[serde(default)]
    pub completed_at: String,
    #[serde(default)]
    pub duration_s: f64,
}

fn default_tier() -> String {
    "headless".into()
}
fn default_status() -> String {
    "running".into()
}

impl MaestroRun {
    pub fn new_with_defaults(
        pattern: String,
        task: String,
        budget: String,
        cwd: String,
        tier: String,
        phases: Vec<serde_yaml::Value>,
    ) -> Self {
        let phases: Vec<Value> = phases
            .into_iter()
            .map(|y| serde_json::to_value(y).unwrap_or(Value::Null))
            .collect();
        Self {
            id: generate_run_id(),
            name: generate_run_name(),
            pattern,
            task,
            budget,
            cwd,
            tier,
            status: "running".into(),
            phases,
            results: vec![],
            started_at: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false),
            completed_at: String::new(),
            duration_s: 0.0,
        }
    }
}

pub fn generate_run_id() -> String {
    let s = Uuid::new_v4().simple().to_string();
    s[..8].to_string()
}

pub fn generate_run_name() -> String {
    Utc::now().format("maestro-%Y%m%d-%H%M%S").to_string()
}

fn detail_json(run: &MaestroRun) -> String {
    json!({
        "phases": run.phases,
        "results": run.results,
        "tier": run.tier,
    })
    .to_string()
}

pub async fn save_run(pool: &SqlitePool, run: &MaestroRun) -> Result<()> {
    let detail = detail_json(run);
    let started = if run.started_at.is_empty() {
        Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false)
    } else {
        run.started_at.clone()
    };
    let completed = if run.completed_at.is_empty() {
        None
    } else {
        Some(run.completed_at.clone())
    };
    let duration = if run.duration_s > 0.0 {
        Some(run.duration_s)
    } else {
        None
    };

    sqlx::query(
        "INSERT INTO dispatch_runs \
         (id, name, pattern, budget, task_summary, cwd, status, started_at, completed_at, duration_s, detail) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11) \
         ON CONFLICT(name) DO UPDATE SET \
            status = excluded.status, \
            completed_at = excluded.completed_at, \
            duration_s = excluded.duration_s, \
            detail = excluded.detail",
    )
    .bind(&run.id)
    .bind(&run.name)
    .bind(&run.pattern)
    .bind(&run.budget)
    .bind(&run.task)
    .bind(&run.cwd)
    .bind(&run.status)
    .bind(&started)
    .bind(completed.as_deref())
    .bind(duration)
    .bind(&detail)
    .execute(pool)
    .await?;
    Ok(())
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct DispatchRunRow {
    pub id: String,
    pub name: String,
    pub pattern: String,
    pub budget: String,
    pub task_summary: String,
    pub cwd: Option<String>,
    pub status: String,
    pub started_at: String,
    pub completed_at: Option<String>,
    pub duration_s: Option<f64>,
    pub detail: Option<String>,
}

pub async fn load_run(pool: &SqlitePool, name: &str) -> Result<Option<Value>> {
    let exact: Option<DispatchRunRow> = sqlx::query_as(
        "SELECT id, name, pattern, budget, task_summary, cwd, status, started_at, \
                completed_at, duration_s, detail \
         FROM dispatch_runs WHERE name = ?1",
    )
    .bind(name)
    .fetch_optional(pool)
    .await?;

    let row = match exact {
        Some(r) => Some(r),
        None => {
            let pattern = format!("{}%", name);
            sqlx::query_as::<_, DispatchRunRow>(
                "SELECT id, name, pattern, budget, task_summary, cwd, status, started_at, \
                        completed_at, duration_s, detail \
                 FROM dispatch_runs WHERE name LIKE ?1 ORDER BY name DESC LIMIT 1",
            )
            .bind(pattern)
            .fetch_optional(pool)
            .await?
        }
    };

    Ok(row.map(|r| {
        let detail_value = r
            .detail
            .as_deref()
            .map(|d| serde_json::from_str::<Value>(d).unwrap_or_else(|_| Value::String(d.to_string())))
            .unwrap_or(Value::Null);
        json!({
            "id": r.id,
            "name": r.name,
            "pattern": r.pattern,
            "budget": r.budget,
            "task_summary": r.task_summary,
            "cwd": r.cwd,
            "status": r.status,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "duration_s": r.duration_s,
            "detail": detail_value,
        })
    }))
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct DispatchRunSummary {
    pub name: String,
    pub pattern: String,
    pub task_summary: String,
    pub status: String,
    pub started_at: String,
    pub duration_s: Option<f64>,
}

pub async fn list_runs(pool: &SqlitePool, limit: i64) -> Result<Vec<DispatchRunSummary>> {
    let rows = sqlx::query_as::<_, DispatchRunSummary>(
        "SELECT name, pattern, task_summary, status, started_at, duration_s \
         FROM dispatch_runs ORDER BY started_at DESC LIMIT ?1",
    )
    .bind(limit)
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

pub fn generate_report(run: &MaestroRun) -> Value {
    let done = run
        .results
        .iter()
        .filter(|r| r.get("status").and_then(|s| s.as_str()) == Some("done"))
        .count();
    json!({
        "name": run.name,
        "pattern": run.pattern,
        "task": run.task,
        "budget": run.budget,
        "duration_s": run.duration_s,
        "agents_completed": done,
        "agents_total": run.results.len(),
        "results": run.results,
    })
}

/// Parse `detail` JSON column, sum durations grouped by tier.
pub async fn tier_stats(pool: &SqlitePool, days: i64) -> Result<Value> {
    let cutoff = (Utc::now() - chrono::Duration::days(days))
        .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let rows = sqlx::query_as::<_, (Option<String>, Option<f64>)>(
        "SELECT detail, duration_s FROM dispatch_runs WHERE started_at > ?1",
    )
    .bind(&cutoff)
    .fetch_all(pool)
    .await?;

    use std::collections::BTreeMap;
    let mut buckets: BTreeMap<String, (i64, f64)> = BTreeMap::new();
    let mut total: i64 = 0;
    for (detail, dur) in rows {
        let tier = detail
            .as_deref()
            .and_then(|s| serde_json::from_str::<Value>(s).ok())
            .and_then(|v| v.get("tier").and_then(|t| t.as_str().map(String::from)))
            .unwrap_or_else(|| "headless".into());
        let entry = buckets.entry(tier).or_insert((0, 0.0));
        entry.0 += 1;
        entry.1 += dur.unwrap_or(0.0);
        total += 1;
    }

    let mut tiers: Vec<Value> = buckets
        .into_iter()
        .map(|(tier, (count, sum_dur))| {
            let avg = if count > 0 { sum_dur / count as f64 } else { 0.0 };
            let pct = if total > 0 {
                (count as f64 / total as f64 * 100.0 * 10.0).round() / 10.0
            } else {
                0.0
            };
            json!({
                "tier": tier,
                "count": count,
                "pct": pct,
                "avg_duration_s": (avg * 10.0).round() / 10.0,
            })
        })
        .collect();
    tiers.sort_by(|a, b| {
        b.get("count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            .cmp(&a.get("count").and_then(|v| v.as_i64()).unwrap_or(0))
    });

    Ok(json!({
        "days": days,
        "total": total,
        "tiers": tiers,
    }))
}
