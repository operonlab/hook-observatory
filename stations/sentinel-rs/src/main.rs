mod config;
mod db;
mod error;

use axum::{routing::get, Json, Router};
use clap::Parser;
use serde_json::json;
use std::sync::Arc;
use std::net::SocketAddr;

use config::Config;

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

    let pool = db::connect(&cfg.database_path).await?;
    tracing::info!("db migrated");

    let state = AppState { cfg: cfg.clone(), pool };

    let app = Router::new()
        .route("/api/sentinel/health", get(health))
        .with_state(state);

    let addr: SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
    tracing::info!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> Json<serde_json::Value> {
    Json(json!({
        "status": "healthy",
        "service": "sentinel-rs",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}
