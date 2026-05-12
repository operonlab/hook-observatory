//! SQLite write helpers shared by guardian + sweep.

use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::SqlitePool;

#[derive(Debug, Clone, Serialize)]
pub struct GuardianAction {
    pub id: String,
    pub ts: DateTime<Utc>,
    pub level: String,        // WARN/CRIT/SWEEP
    pub priority: String,     // P1/P2/P3/SWEEP-*
    pub pid: Option<i32>,
    pub process_name: String,
    pub mem_mb: f64,
    pub cpu_pct: f64,
    pub action: String,       // TERM/SIGCHLD/SKIP
    pub result: String,       // success/already_dead/failed/skipped/warn/no_permission
    pub detail: Option<String>,
}

impl GuardianAction {
    pub fn new(
        level: &str,
        priority: &str,
        pid: Option<i32>,
        process_name: impl Into<String>,
        mem_mb: f64,
        cpu_pct: f64,
        action: &str,
        result: &str,
        detail: Option<String>,
    ) -> Self {
        Self {
            id: uuid::Uuid::new_v4().simple().to_string(),
            ts: Utc::now(),
            level: level.into(),
            priority: priority.into(),
            pid,
            process_name: process_name.into(),
            mem_mb,
            cpu_pct,
            action: action.into(),
            result: result.into(),
            detail,
        }
    }
}

pub async fn insert_guardian_actions(
    pool: &SqlitePool,
    actions: &[GuardianAction],
) -> Result<u64> {
    if actions.is_empty() {
        return Ok(0);
    }
    let mut tx = pool.begin().await?;
    let mut written = 0;
    for a in actions {
        sqlx::query(
            "INSERT INTO guardian_actions \
             (id, ts, level, priority, pid, process_name, mem_mb, cpu_pct, action, result, detail) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )
        .bind(&a.id)
        .bind(a.ts.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false))
        .bind(&a.level)
        .bind(&a.priority)
        .bind(a.pid)
        .bind(&a.process_name)
        .bind(a.mem_mb)
        .bind(a.cpu_pct)
        .bind(&a.action)
        .bind(&a.result)
        .bind(a.detail.as_deref())
        .execute(&mut *tx)
        .await?;
        written += 1;
    }
    tx.commit().await?;
    Ok(written)
}
