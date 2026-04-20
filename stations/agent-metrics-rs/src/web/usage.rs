//! /usage/* routes.

use super::AppState;
use axum::{
    extract::{Query, State},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct DaysQuery {
    #[serde(default = "default_days")]
    pub days: i64,
}
fn default_days() -> i64 {
    30
}

pub async fn budget(State(state): State<AppState>) -> Json<Value> {
    let r = crate::collectors::usage::get_month_to_date(&state.settings).await;
    Json(serde_json::to_value(r).unwrap_or(Value::Null))
}

pub async fn by_model(
    State(state): State<AppState>,
    Query(q): Query<DaysQuery>,
) -> Json<Value> {
    let r = crate::collectors::usage::get_model_breakdown(&state.settings, q.days).await;
    Json(serde_json::to_value(r).unwrap_or(Value::Null))
}

pub async fn daily_cost(State(state): State<AppState>) -> Json<Value> {
    let r = crate::collectors::usage::get_today_cost(&state.settings).await;
    Json(serde_json::to_value(r).unwrap_or(Value::Null))
}

pub async fn summary_stub() -> Json<Value> {
    Json(json!({}))
}

pub async fn trends_stub() -> Json<Value> {
    Json(json!({"daily": []}))
}

pub async fn subscription_stub() -> Json<Value> {
    Json(json!({"providers": []}))
}
