//! HTTP layer — axum routes + dashboard.
//!
//! Wires every Phase 3 collector into the same paths the Python FastAPI app
//! exposed, so existing frontend (`templates/index.html` + `static/js/app.js`)
//! and tmux/CLI consumers see no protocol change.

use crate::config::Settings;
use crate::loops::LoopState;
use axum::Router;
use sqlx::SqlitePool;
use std::sync::Arc;

pub mod dashboard;
pub mod litellm;
pub mod logs;
pub mod sysmon;
pub mod usage;

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<Settings>,
    pub pool: SqlitePool,
    pub loop_state: LoopState,
}

pub fn build_router(state: AppState) -> Router {
    use axum::routing::get;

    let api = Router::new()
        // health
        .route("/health", get(health))
        // dashboard html
        .route("/", get(dashboard::index))
        // litellm
        .route("/litellm/status", get(litellm::status))
        .route("/litellm/model-catalog", get(litellm::model_catalog))
        // usage
        .route("/usage/budget", get(usage::budget))
        .route("/usage/by-model", get(usage::by_model))
        .route("/usage/daily-cost", get(usage::daily_cost))
        .route("/usage/summary", get(usage::summary_stub))
        .route("/usage/trends", get(usage::trends_stub))
        .route("/usage/subscription", get(usage::subscription_stub))
        // sysmon + quota
        .route("/sysmon/current", get(sysmon::current))
        .route("/sysmon/history", get(sysmon::history))
        .route("/quota/current", get(sysmon::quota_current))
        .route("/quota/formatted", get(sysmon::quota_formatted))
        // guardian + sweep logs
        .route("/guardian/log", get(logs::guardian_log))
        .route("/sweep/log", get(logs::sweep_log));

    let static_dir = std::path::PathBuf::from(&state.settings.static_dir);
    let api = if static_dir.exists() {
        api.nest_service(
            "/static",
            tower_http::services::ServeDir::new(&static_dir),
        )
    } else {
        api
    };

    api.with_state(state)
        .layer(tower_http::cors::CorsLayer::permissive())
        .layer(tower_http::trace::TraceLayer::new_for_http())
}

async fn health() -> axum::Json<serde_json::Value> {
    axum::Json(serde_json::json!({
        "status": "ok",
        "service": "agent-metrics-rs",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}
