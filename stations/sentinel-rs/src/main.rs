mod checker;
mod config;
mod db;
mod error;
mod models;
mod sse;
mod state;
mod tasks;

use axum::extract::{Path, State};
use axum::{routing::get, Json, Router};
use clap::Parser;
use serde_json::json;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use config::Config;
use state::InterventionEngine;

#[derive(Parser, Debug)]
#[command(name = "sentinel-rs", about = "Workshop sentinel (Rust + SQLite)")]
struct Cli {
    #[arg(long, default_value = "config.yaml")]
    config: String,
}

#[derive(Clone)]
struct AppState {
    cfg: Arc<Config>,
    pool: sqlx::SqlitePool,
    engine: Arc<InterventionEngine>,
    sse: sse::SseHub,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "sentinel_rs=info,tower_http=info".into()),
        )
        .init();

    let cli = Cli::parse();
    let cfg = Arc::new(Config::load(&cli.config)?);
    tracing::info!(port = cfg.port, db = %cfg.database_path.display(), "sentinel-rs starting");

    std::fs::create_dir_all(&cfg.lock_dir).ok();
    std::fs::create_dir_all(&cfg.log_dir).ok();

    let pool = db::connect(&cfg.database_path).await?;
    tracing::info!("db migrated");

    let engine = Arc::new(InterventionEngine::new(cfg.clone()));
    let sse_hub = sse::SseHub::new(256);
    let token = CancellationToken::new();

    // Spawn background tasks
    let light_handle = {
        let e = engine.clone();
        let p = pool.clone();
        let s = sse_hub.clone();
        let t = token.clone();
        let interval = cfg.check_light_interval_sec;
        tokio::spawn(async move { tasks::light_loop::run(e, p, s, interval, t).await })
    };

    let purge_handle = {
        let p = pool.clone();
        let t = token.clone();
        let interval = cfg.purge_interval_sec;
        let days = cfg.purge_retention_days;
        tokio::spawn(async move { tasks::purge_loop::run(p, interval, days, t).await })
    };

    let state = AppState {
        cfg: cfg.clone(),
        pool,
        engine,
        sse: sse_hub,
    };

    let app = Router::new()
        .route("/api/sentinel/health", get(health))
        .route("/api/sentinel/status", get(status_all))
        .route("/api/sentinel/status/:service", get(status_one))
        .with_state(state);

    let addr: SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
    tracing::info!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;

    let shutdown_token = token.clone();
    let server = axum::serve(listener, app).with_graceful_shutdown(async move {
        let _ = tokio::signal::ctrl_c().await;
        tracing::info!("shutdown signal received");
        shutdown_token.cancel();
    });

    if let Err(e) = server.await {
        tracing::error!("server error: {}", e);
    }

    // Wait tasks to drain
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), light_handle).await;
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), purge_handle).await;
    Ok(())
}

async fn health() -> Json<serde_json::Value> {
    Json(json!({
        "status": "healthy",
        "service": "sentinel-rs",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}

async fn status_all(State(s): State<AppState>) -> Json<serde_json::Value> {
    Json(tasks::light_loop::build_status_payload(&s.engine))
}

async fn status_one(
    State(s): State<AppState>,
    Path(service): Path<String>,
) -> Result<Json<serde_json::Value>, error::SentinelError> {
    let t = s.engine.get_or_create(&service);
    if t.light_status.is_none() {
        return Err(error::SentinelError::NotFound(format!(
            "no data for {}",
            service
        )));
    }
    Ok(Json(json!({
        "service": t.service,
        "state": t.state,
        "light_status": t.light_status,
        "response_ms": t.response_ms,
        "last_light_check": t.last_light_check,
        "first_failure_at": t.first_failure_at,
        "agent_id": t.agent_id,
        "incident_id": t.incident_id,
    })))
}
