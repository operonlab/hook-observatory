//! /ingest, /current, /sessions, /sessions/{sid}, /history routes.

use super::AppState;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::{Duration, Utc};
use serde::Deserialize;
use serde_json::{json, Value};

pub async fn ingest(
    State(state): State<AppState>,
    Json(req): Json<crate::session::IngestRequest>,
) -> Json<Value> {
    let resp = state.session_store.ingest(req).await;
    Json(serde_json::to_value(resp).unwrap_or(Value::Null))
}

pub async fn current(State(state): State<AppState>) -> Json<Value> {
    let snap = state.session_store.get_snapshot().await;
    let has_sessions = snap
        .get("sessions")
        .and_then(|v| v.as_array())
        .map(|a| !a.is_empty())
        .unwrap_or(false);
    if has_sessions {
        return Json(snap);
    }
    // Fallback: file
    if let Ok(text) = std::fs::read_to_string(&state.settings.fallback_path) {
        if let Ok(v) = serde_json::from_str::<Value>(&text) {
            return Json(v);
        }
    }
    Json(json!({
        "date": "",
        "total_cost_usd": 0,
        "active_sessions": 0,
        "sessions": []
    }))
}

#[derive(Deserialize)]
pub struct SessionsQuery {
    #[serde(default = "default_true")]
    pub active_only: bool,
}
fn default_true() -> bool {
    true
}

pub async fn list_sessions(
    State(state): State<AppState>,
    Query(q): Query<SessionsQuery>,
) -> Json<Value> {
    if q.active_only {
        let sessions = state.session_store.get_active_sessions().await;
        let count = sessions.len();
        return Json(json!({"sessions": sessions, "count": count}));
    }
    let rows = sqlx::query_as::<_, SessionRow>(
        "SELECT id, sid, cli, model_id, model_display, project, cost_usd, context_used_pct, \
         context_window_size, input_tokens, output_tokens, cache_creation_tokens, \
         cache_read_tokens, first_seen, last_seen, is_active \
         FROM sessions ORDER BY last_seen DESC LIMIT 100",
    )
    .fetch_all(&state.pool)
    .await
    .unwrap_or_default();
    let count = rows.len();
    Json(json!({"sessions": rows, "count": count}))
}

#[derive(Deserialize)]
pub struct SessionDetailQuery {
    #[serde(default)]
    pub snapshots: bool,
}

pub async fn get_session(
    State(state): State<AppState>,
    Path(sid): Path<String>,
    Query(q): Query<SessionDetailQuery>,
) -> Result<Json<Value>, StatusCode> {
    // In-memory first
    for s in state.session_store.get_active_sessions().await {
        if s.sid == sid || s.id.starts_with(&sid) {
            let id = s.id.clone();
            let mut result = json!({"session": s});
            if q.snapshots {
                let snaps = fetch_session_snapshots(&state, &id).await;
                result["snapshots"] = json!(snaps);
            }
            return Ok(Json(result));
        }
    }

    // SQLite
    let pattern = format!("{}%", sid);
    let row: Option<SessionRow> = sqlx::query_as::<_, SessionRow>(
        "SELECT id, sid, cli, model_id, model_display, project, cost_usd, context_used_pct, \
         context_window_size, input_tokens, output_tokens, cache_creation_tokens, \
         cache_read_tokens, first_seen, last_seen, is_active \
         FROM sessions WHERE sid = ?1 OR id LIKE ?2",
    )
    .bind(&sid)
    .bind(&pattern)
    .fetch_optional(&state.pool)
    .await
    .unwrap_or(None);
    let row = row.ok_or(StatusCode::NOT_FOUND)?;
    let id = row.id.clone();
    let mut result = json!({"session": row});
    if q.snapshots {
        let snaps = fetch_session_snapshots(&state, &id).await;
        result["snapshots"] = json!(snaps);
    }
    Ok(Json(result))
}

async fn fetch_session_snapshots(state: &AppState, session_id: &str) -> Vec<crate::session::SnapshotRow> {
    sqlx::query_as::<_, crate::session::SnapshotRow>(
        "SELECT id, ts, session_id, sid, cli, cost_usd, context_used_pct, input_tokens, output_tokens \
         FROM snapshots WHERE session_id = ?1 ORDER BY ts DESC LIMIT 1000",
    )
    .bind(session_id)
    .fetch_all(&state.pool)
    .await
    .unwrap_or_default()
}

#[derive(Deserialize)]
pub struct HistoryQuery {
    #[serde(default = "default_history_days")]
    pub days: i64,
}
fn default_history_days() -> i64 {
    7
}

pub async fn history(
    State(state): State<AppState>,
    Query(q): Query<HistoryQuery>,
) -> Json<Value> {
    let cutoff = (Utc::now() - Duration::days(q.days)).format("%Y-%m-%d").to_string();
    let summaries = sqlx::query_as::<_, crate::session::DailySummaryRow>(
        "SELECT id, date, total_cost_usd, total_sessions, peak_concurrent, \
         total_input_tokens, total_output_tokens, avg_context_pct, max_context_pct \
         FROM daily_summary WHERE date >= ?1 ORDER BY date DESC",
    )
    .bind(&cutoff)
    .fetch_all(&state.pool)
    .await
    .unwrap_or_default();
    let count = summaries.len();
    Json(json!({"days": q.days, "summaries": summaries, "count": count}))
}

#[derive(Debug, Clone, sqlx::FromRow, serde::Serialize)]
pub struct SessionRow {
    pub id: String,
    pub sid: String,
    pub cli: String,
    pub model_id: String,
    pub model_display: String,
    pub project: String,
    pub cost_usd: f64,
    pub context_used_pct: f64,
    pub context_window_size: i64,
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub cache_creation_tokens: i64,
    pub cache_read_tokens: i64,
    pub first_seen: String,
    pub last_seen: String,
    pub is_active: i64,
}
