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
pub mod maestro;
pub mod projects;
pub mod sessions;
pub mod sse;
pub mod sysmon;
pub mod usage;

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<Settings>,
    pub pool: SqlitePool,
    pub loop_state: LoopState,
    pub session_store: crate::session::SessionStore,
    pub event_bus: sse::EventBus,
}

pub fn build_router(state: AppState) -> Router {
    use axum::routing::get;

    let api = Router::new()
        // health
        .route("/health", get(health))
        // dashboard html
        .route("/", get(dashboard::index))
        // SSE stream — replaces 5 setInterval polls in app.js
        .route("/events/stream", get(sse::stream_handler))
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
        .route("/sweep/log", get(logs::sweep_log))
        // sessions / ingest / current / history
        .route("/ingest", axum::routing::post(sessions::ingest))
        .route("/current", get(sessions::current))
        .route("/sessions", get(sessions::list_sessions))
        .route("/sessions/:sid", get(sessions::get_session))
        .route("/history", get(sessions::history))
        // maestro orchestration
        .route("/maestro/plan", axum::routing::post(maestro::plan))
        .route("/maestro/run", axum::routing::post(maestro::run_dispatch))
        .route("/maestro/runs", get(maestro::list_runs))
        .route("/maestro/runs/:name", get(maestro::get_run))
        .route("/maestro/tier-stats", get(maestro::tier_stats))
        .route("/maestro/routing-table", get(maestro::routing_table))
        // projects (team-task)
        .route("/projects/", get(projects::list_projects).post(projects::create_project))
        .route("/projects/:name", get(projects::get_project))
        .route("/projects/:name/tasks", axum::routing::post(projects::add_task))
        .route("/projects/:name/ready", get(projects::ready_tasks))
        .route("/projects/:name/next", get(projects::next_stage))
        .route("/projects/:name/tasks/:task_id", axum::routing::patch(projects::update_task))
        .route("/projects/:name/tasks/:task_id/result", axum::routing::post(projects::record_result))
        .route("/projects/:name/debaters", axum::routing::post(projects::add_debater))
        .route("/projects/:name/rounds", axum::routing::post(projects::manage_round))
        .route("/projects/:name/reset", axum::routing::post(projects::reset_project));

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
        "service": "agent-metrics",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}
