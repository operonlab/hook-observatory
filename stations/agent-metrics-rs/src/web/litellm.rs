//! /litellm/* routes.

use super::AppState;
use axum::{extract::State, Json};
use redis::AsyncCommands;
use serde_json::{json, Value};

pub async fn status(State(state): State<AppState>) -> Json<Value> {
    let r = crate::collectors::litellm::get_litellm_status(&state.settings).await;
    Json(serde_json::to_value(r).unwrap_or(Value::Null))
}

const FALLBACK_JSON: &str = include_str!("../../data/model_catalog_fallback.json");
const REDIS_KEY: &str = "agent-metrics:model-catalog:full";

async fn open_redis(url: &str) -> Option<redis::aio::ConnectionManager> {
    let client = redis::Client::open(url.to_string()).ok()?;
    redis::aio::ConnectionManager::new(client).await.ok()
}

async fn dynamic_catalog(state: &AppState) -> Option<Value> {
    let mut conn = open_redis(&state.settings.redis_url).await?;
    let raw: Option<String> = conn.get(REDIS_KEY).await.ok();
    raw.and_then(|s| serde_json::from_str(&s).ok())
}

pub async fn model_catalog(State(state): State<AppState>) -> Json<Value> {
    let fallback: Value = serde_json::from_str(FALLBACK_JSON).expect("fallback JSON valid");

    let dynamic = dynamic_catalog(&state).await;

    if let Some(d) = dynamic {
        let synced_at = d.get("synced_at").cloned().unwrap_or(Value::Null);
        let source_count = d.get("source_count").cloned().unwrap_or(Value::from("?"));
        let synced_at_short = synced_at
            .as_str()
            .map(|s| s.chars().take(10).collect::<String>())
            .unwrap_or_else(|| "?".into());
        return Json(json!({
            "catalog": fallback["catalog"],
            "highlights_subjective": d.get("highlights_subjective").cloned().unwrap_or(fallback["highlights_subjective"].clone()),
            "highlights_benchmark": d.get("highlights_benchmark").cloned().unwrap_or(fallback["highlights_benchmark"].clone()),
            "notable_unconfigured": {
                "models": d.get("notable_unconfigured").cloned().unwrap_or(fallback["notable_unconfigured"].clone()),
                "synced_at": synced_at,
            },
            "scenarios": d.get("scenarios").cloned().unwrap_or(fallback["scenarios"].clone()),
            "synced_at": d.get("synced_at").cloned().unwrap_or(Value::Null),
            "data_sources": {
                "sources_used": d.get("sources_used").cloned().unwrap_or(json!([])),
                "source_count": source_count.clone(),
                "note": format!("Consensus ranking from {} sources ({})", source_count, synced_at_short),
            }
        }));
    }

    Json(json!({
        "catalog": fallback["catalog"],
        "highlights_subjective": fallback["highlights_subjective"],
        "highlights_benchmark": fallback["highlights_benchmark"],
        "notable_unconfigured": {
            "models": fallback["notable_unconfigured"],
            "synced_at": fallback["fallback_synced_at"],
        },
        "scenarios": fallback["scenarios"],
        "synced_at": Value::Null,
        "data_sources": fallback["fallback_data_sources"],
    }))
}
