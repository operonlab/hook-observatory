//! /guardian/log + /sweep/log routes — query SQLite guardian_actions table.

use super::AppState;
use axum::{
    extract::{Query, State},
    Json,
};
use chrono::{Duration, Utc};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct LogQuery {
    #[serde(default = "default_hours")]
    pub hours: i64,
    pub level: Option<String>,
}
fn default_hours() -> i64 {
    24
}

pub async fn guardian_log(
    State(state): State<AppState>,
    Query(q): Query<LogQuery>,
) -> Json<Value> {
    let cutoff = (Utc::now() - Duration::hours(q.hours))
        .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let mut sql = "SELECT id, ts, level, priority, pid, process_name, mem_mb, cpu_pct, action, result, detail \
                   FROM guardian_actions WHERE ts > ?1 AND level != 'SWEEP'"
        .to_string();
    if q.level.is_some() {
        sql.push_str(" AND level = ?2");
    }
    sql.push_str(" ORDER BY ts DESC LIMIT 200");

    let actions = match q.level {
        Some(l) => sqlx::query_as::<_, GuardianRow>(&sql)
            .bind(&cutoff)
            .bind(l)
            .fetch_all(&state.pool)
            .await,
        None => sqlx::query_as::<_, GuardianRow>(&sql)
            .bind(&cutoff)
            .fetch_all(&state.pool)
            .await,
    };
    let actions = actions.unwrap_or_default();
    let total = actions.len();
    Json(json!({"actions": actions, "total": total}))
}

pub async fn sweep_log(
    State(state): State<AppState>,
    Query(q): Query<LogQuery>,
) -> Json<Value> {
    let cutoff = (Utc::now() - Duration::hours(q.hours))
        .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let actions = sqlx::query_as::<_, GuardianRow>(
        "SELECT id, ts, level, priority, pid, process_name, mem_mb, cpu_pct, action, result, detail \
         FROM guardian_actions WHERE ts > ?1 AND level = 'SWEEP' ORDER BY ts DESC LIMIT 200",
    )
    .bind(&cutoff)
    .fetch_all(&state.pool)
    .await
    .unwrap_or_default();
    let total = actions.len();
    Json(json!({"actions": actions, "total": total}))
}

#[derive(Debug, sqlx::FromRow, serde::Serialize)]
pub struct GuardianRow {
    pub id: String,
    pub ts: String,
    pub level: String,
    pub priority: String,
    pub pid: Option<i64>,
    pub process_name: String,
    pub mem_mb: Option<f64>,
    pub cpu_pct: Option<f64>,
    pub action: String,
    pub result: String,
    pub detail: Option<String>,
}
