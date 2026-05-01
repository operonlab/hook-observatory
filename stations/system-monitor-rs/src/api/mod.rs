//! HTTP API. Mirrors `stations/system-monitor/api.py` 1:1 — same paths, same
//! JSON shapes — so SDK clients and the dashboard frontend keep working.

use anyhow::Result;
use axum::{
    extract::{Path, State},
    response::{Html, IntoResponse, Json},
    routing::{get, post},
    Router,
};
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;

use crate::collector::{collect_all, Collector};
use crate::config::Settings;

pub mod sse;

const STATUS_CACHE_TTL: Duration = Duration::from_secs(30);

#[derive(Clone)]
pub struct AppState {
    pub cfg: Settings,
    pub collector: Arc<Collector>,
    pub broadcaster: sse::Broadcaster,
    pub status_cache: Arc<RwLock<Option<(Instant, Value)>>>,
}

pub async fn build_router(cfg: Settings) -> Result<Router> {
    let collector = Arc::new(Collector::new());
    let broadcaster = sse::Broadcaster::new();
    let state = AppState {
        cfg: cfg.clone(),
        collector: collector.clone(),
        broadcaster: broadcaster.clone(),
        status_cache: Arc::new(RwLock::new(None)),
    };

    // Spawn background broadcasters.
    sse::spawn_dashboard_loop(state.clone());
    sse::spawn_disk_loop(state.clone());

    Ok(Router::new()
        .route("/", get(dashboard))
        .route("/sw.js", get(service_worker))
        .route("/health", get(health))
        .route("/status", get(status))
        .route("/history", get(history))
        .route("/alerts", get(alerts))
        .route("/services", get(services_list))
        .route("/services/:label/enable", post(service_enable))
        .route("/services/:label/disable", post(service_disable))
        .route("/services/:label/restart", post(service_restart))
        .route("/services/:label/logs", get(service_logs))
        .route("/disk/summary", get(disk_summary))
        .route("/disk/scan", get(disk_scan))
        .route("/disk/delete", post(disk_delete))
        .route("/disk/clean-cache", post(disk_clean_cache))
        .route("/disk/empty-trash", post(disk_empty_trash))
        .route("/guardian", get(guardian_get))
        .route("/guardian/run", post(guardian_run))
        .route("/guardian/compressed-sweep", post(guardian_compressed_sweep))
        .route("/reports", get(reports_list))
        .route("/reports/:filename", get(report_get))
        .route("/events/stream", get(sse::stream))
        .with_state(state))
}

// ── routes ───────────────────────────────────────────────────────────────────

async fn dashboard() -> impl IntoResponse {
    Html(include_str!("../../templates/index.html"))
}

async fn service_worker() -> impl IntoResponse {
    (
        [("content-type", "application/javascript")],
        include_str!("../../static/sw.js"),
    )
}

async fn health(State(s): State<AppState>) -> Json<Value> {
    Json(json!({
        "status": "ok",
        "service": "system-monitor-rs",
        "version": env!("CARGO_PKG_VERSION"),
        "hostname": s.cfg.hostname,
    }))
}

async fn status(State(s): State<AppState>) -> Json<Value> {
    // Read-through cache (mirrors Python CACHE_TTL=30s) — keeps /status under
    // 5ms on the hot path while the heavy `top -l 1` shell-out only fires
    // every 30s.
    {
        let guard = s.status_cache.read().await;
        if let Some((stamp, ref cached)) = *guard {
            if stamp.elapsed() < STATUS_CACHE_TTL {
                return Json(cached.clone());
            }
        }
    }
    match collect_all(&s.collector).await {
        Ok(v) => {
            let mut guard = s.status_cache.write().await;
            *guard = Some((Instant::now(), v.clone()));
            Json(v)
        }
        Err(e) => Json(json!({"error": e.to_string()})),
    }
}

async fn history(State(s): State<AppState>) -> Json<Value> {
    Json(crate::store::list_snapshots(&s.cfg, 30).unwrap_or_else(|_| json!([])))
}

async fn alerts(State(s): State<AppState>) -> Json<Value> {
    Json(crate::store::list_alerts(&s.cfg).unwrap_or_else(|_| json!([])))
}

async fn services_list() -> Json<Value> {
    let items = crate::collector::services::list().await.unwrap_or_default();
    Json(json!(items))
}

async fn service_enable(Path(label): Path<String>) -> Json<Value> {
    Json(crate::scheduler::enable(&label).await.unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn service_disable(Path(label): Path<String>) -> Json<Value> {
    Json(crate::scheduler::disable(&label).await.unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn service_restart(Path(label): Path<String>) -> Json<Value> {
    Json(crate::scheduler::restart(&label).await.unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn service_logs(Path(label): Path<String>) -> Json<Value> {
    Json(crate::scheduler::logs(&label, 50).await.unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn disk_summary(State(s): State<AppState>) -> Json<Value> {
    Json(crate::collector::disk_fast::collect(&s.collector).await.unwrap_or_else(|_| json!({})))
}

async fn disk_scan() -> Json<Value> {
    Json(crate::collector::disk_deep::collect().await.unwrap_or_else(|_| json!({})))
}

async fn disk_delete(axum::extract::Json(body): axum::extract::Json<Value>) -> Json<Value> {
    let path = body.get("path").and_then(|v| v.as_str()).unwrap_or("");
    Json(crate::disk_manager::delete_path(path).unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn disk_clean_cache(axum::extract::Json(body): axum::extract::Json<Value>) -> Json<Value> {
    let path = body.get("path").and_then(|v| v.as_str()).unwrap_or("");
    Json(crate::disk_manager::clean_cache_dir(path).unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn disk_empty_trash() -> Json<Value> {
    Json(crate::disk_manager::empty_trash().unwrap_or_else(|e| {
        json!({"ok": false, "error": e.to_string()})
    }))
}

async fn guardian_get(State(s): State<AppState>) -> Json<Value> {
    Json(crate::guardian::get_state(&s.cfg).unwrap_or_else(|_| json!({"entries": []})))
}

async fn guardian_run(State(s): State<AppState>) -> Json<Value> {
    match crate::guardian::tick(&s.cfg, false).await {
        Ok(()) => Json(json!({"ok": true})),
        Err(e) => Json(json!({"ok": false, "error": e.to_string()})),
    }
}

async fn guardian_compressed_sweep() -> Json<Value> {
    Json(json!({"ok": true, "swept": false, "note": "no-op (monitor-only)"}))
}

async fn reports_list(State(s): State<AppState>) -> Json<Value> {
    Json(crate::reporter::list(&s.cfg).unwrap_or_else(|_| json!([])))
}

async fn report_get(State(s): State<AppState>, Path(filename): Path<String>) -> Json<Value> {
    Json(crate::reporter::get(&s.cfg, &filename).unwrap_or_else(|e| {
        json!({"error": e.to_string()})
    }))
}
