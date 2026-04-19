use anyhow::Result;
use axum::{routing::get, Json, Router};
use serde_json::json;
use std::net::SocketAddr;
use tracing_subscriber::EnvFilter;

mod analyzer;
mod config;
mod db;
mod filler;
mod line;
mod models;
mod notify;
mod ocr_client;
mod orchestrator;
mod playwright;
mod recon;
mod web;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cfg = config::Settings::from_env();
    tracing::info!("auto-survey-rs starting on port {}", cfg.web_port);

    let pool = db::init_pool(&cfg.sqlite_path).await?;
    sqlx::migrate!("./migrations").run(&pool).await?;

    let state = web::AppState {
        pool,
        cfg: cfg.clone(),
    };

    let app = Router::new()
        .route("/status", get(status))
        .route("/health", get(status))
        .merge(web::routes())
        .with_state(state);

    let addr: SocketAddr = format!("127.0.0.1:{}", cfg.web_port).parse()?;
    tracing::info!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}

async fn status() -> Json<serde_json::Value> {
    Json(json!({
        "service": "auto-survey-rs",
        "version": env!("CARGO_PKG_VERSION"),
        "status": "ok",
    }))
}
