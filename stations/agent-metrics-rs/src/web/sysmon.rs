//! /sysmon/* and /quota/* routes.

use super::AppState;
use axum::{
    extract::{Query, State},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct HistoryQuery {
    #[serde(default = "default_minutes")]
    pub minutes: i64,
}
fn default_minutes() -> i64 {
    60
}

pub async fn current(State(state): State<AppState>) -> Json<Value> {
    let latest = state.loop_state.latest.read().await.clone();
    match latest {
        Some(snap) => Json(serde_json::to_value(snap).unwrap_or(Value::Null)),
        None => Json(json!({"error": "no data yet"})),
    }
}

pub async fn history(
    State(state): State<AppState>,
    Query(q): Query<HistoryQuery>,
) -> Json<Value> {
    let interval_s = state.settings.sysmon_collect_interval as i64;
    let max_entries = if q.minutes <= 0 || interval_s <= 0 {
        0
    } else {
        ((q.minutes * 60) / interval_s) as usize
    };
    let buf = state.loop_state.history.read().await;
    let take = buf.len().min(max_entries);
    let entries: Vec<_> = buf.iter().rev().take(take).collect::<Vec<_>>().into_iter().rev().collect();
    let entries_json: Vec<Value> = entries.iter().map(|s| serde_json::to_value(s).unwrap_or(Value::Null)).collect();
    Json(json!({"entries": entries_json, "interval_s": interval_s}))
}

pub async fn quota_current(State(state): State<AppState>) -> Json<Value> {
    let formatted = crate::collectors::quota::get_quota(&state.settings).await;
    let raw = crate::collectors::quota::get_raw_cache(&state.settings).await;
    Json(json!({
        "raw": raw,
        "health": Value::Null,
        "parsed": {"cc": {}, "cx": {}, "gm": {}},
        "formatted": {
            "cc_5h": formatted.llm_cc_5h,
            "cc_7d": formatted.llm_cc_7d,
            "cc_ex": formatted.llm_cc_ex,
            "cx_5h": formatted.llm_cx_5h,
            "cx_7d": formatted.llm_cx_7d,
            "gm_pro": formatted.llm_gm_pro,
            "gm_flash": formatted.llm_gm_flash,
            "cc_5h_resets_at": formatted.llm_cc_5h_resets_at,
            "cc_7d_resets_at": formatted.llm_cc_7d_resets_at,
            "cx_5h_resets_at": formatted.llm_cx_5h_resets_at,
            "cx_7d_resets_at": formatted.llm_cx_7d_resets_at,
            "gm_daily_resets_at": formatted.llm_gm_daily_resets_at,
            "cc_ex_used_usd": formatted.llm_cc_ex_used_usd,
            "cc_ex_limit_usd": formatted.llm_cc_ex_limit_usd,
            "cc_ex_balance_usd": formatted.llm_cc_ex_balance_usd,
            "cc_ex_utilization": formatted.llm_cc_ex_utilization,
            "cc_ex_enabled": formatted.llm_cc_ex_enabled,
        }
    }))
}

pub async fn quota_formatted(State(state): State<AppState>) -> Json<Value> {
    let q = crate::collectors::quota::get_quota(&state.settings).await;
    Json(json!({
        "cc-5h": q.llm_cc_5h,
        "cc-7d": q.llm_cc_7d,
        "cc-ex": q.llm_cc_ex,
        "cx-5h": q.llm_cx_5h,
        "cx-7d": q.llm_cx_7d,
        "gm-pro": q.llm_gm_pro,
        "gm-flash": q.llm_gm_flash,
        "display": q.llm_display,
    }))
}
