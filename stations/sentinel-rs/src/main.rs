mod checker;
mod config;
mod db;
mod error;
mod models;
mod notify;
mod prompt_templates;
mod push;
mod remediation;
mod routes;
mod sse;
mod state;
mod tasks;

use axum::{
    routing::{get, post},
    Router,
};
use clap::Parser;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use tower_http::services::{ServeDir, ServeFile};

use config::Config;
use state::InterventionEngine;

#[derive(Parser, Debug)]
#[command(name = "sentinel-rs", about = "Workshop sentinel (Rust + SQLite)")]
struct Cli {
    #[arg(long, default_value = "config.yaml")]
    config: String,
}

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub pool: sqlx::SqlitePool,
    pub engine: Arc<InterventionEngine>,
    pub sse: sse::SseHub,
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
    let remediator = Arc::new(remediation::Remediator::new(engine.clone(), pool.clone(), cfg.clone()));
    let sse_hub = sse::SseHub::new(256);
    let token = CancellationToken::new();

    let light_handle = {
        let e = engine.clone();
        let p = pool.clone();
        let s = sse_hub.clone();
        let t = token.clone();
        let interval = cfg.check_light_interval_sec;
        tokio::spawn(async move { tasks::light_loop::run(e, p, s, interval, t).await })
    };

    let repair_handle = {
        let e = engine.clone();
        let r = remediator.clone();
        let t = token.clone();
        let cooldown = cfg.notification_cooldown_sec;
        let interval = cfg.repair_monitor_interval_sec;
        tokio::spawn(async move { tasks::repair_loop::run(e, r, cooldown, interval, t).await })
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

    let static_dir: PathBuf = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("static");
    let index_path = static_dir.join("index.html");

    let app = Router::new()
        .route("/api/sentinel/health", get(routes::health))
        .route("/api/sentinel/status", get(routes::status_all))
        .route("/api/sentinel/status/:service", get(routes::status_one))
        .route("/api/sentinel/notify", post(routes::notify))
        .route("/api/sentinel/resolve", post(routes::resolve))
        .route("/api/sentinel/operations", get(routes::operations))
        .route("/api/sentinel/incidents", get(routes::incidents_list))
        .route("/api/sentinel/incidents/:id", get(routes::incident_detail))
        .route("/api/sentinel/uptime", get(routes::uptime))
        .route("/api/sentinel/subscribe", post(routes::subscribe))
        .route("/api/sentinel/events", get(routes::sse_events))
        .route(
            "/api/sysmon/*subpath",
            get(routes::sysmon_proxy).post(routes::sysmon_proxy),
        )
        .route_service("/", ServeFile::new(&index_path))
        .nest_service("/static", ServeDir::new(&static_dir))
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

    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), light_handle).await;
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), repair_handle).await;
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), purge_handle).await;
    Ok(())
}
