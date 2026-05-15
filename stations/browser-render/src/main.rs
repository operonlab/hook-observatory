//! Workshop browser-render station — offline web → frames renderer.
//!
//! HTTP API:
//!   GET  /healthz
//!   POST /render     body = RenderRequest  → RenderResult
//!   POST /shutdown   (dev-mode only when --dev is passed)

mod api;

use axum::{
    routing::{get, post},
    Router,
};
use clap::Parser;
use std::net::SocketAddr;
use std::sync::Arc;

use api::AppState;
use browser_render::config::Config;

#[derive(Parser, Debug)]
#[command(name = "browser-render", about = "Workshop offline web → frames renderer")]
struct Cli {
    #[arg(long, default_value = "config.yaml")]
    config: String,
    /// Enable POST /shutdown endpoint (dev only).
    #[arg(long)]
    dev: bool,
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "browser_render=info,tower_http=info".into()),
        )
        .init();

    let cli = Cli::parse();
    let cfg = match Config::load(&cli.config) {
        Ok(c) => Arc::new(c),
        Err(e) => {
            tracing::warn!("config load failed ({e}); using defaults");
            Arc::new(Config {
                host: "127.0.0.1".into(),
                port: 10221,
                default_fps: 30,
                default_viewport: [1920, 1080],
                chromium_path: String::new(),
            })
        }
    };
    tracing::info!(host=%cfg.host, port=cfg.port, "browser-render starting");

    let state = AppState { cfg: cfg.clone() };

    let mut app = Router::new()
        .route("/healthz", get(api::healthz))
        .route("/render", post(api::render_endpoint));
    if cli.dev {
        app = app.route("/shutdown", post(api::shutdown));
        tracing::warn!("dev mode: /shutdown enabled");
    }
    let app = app.with_state(state);

    let addr: SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("listening on http://{}", addr);

    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
            tracing::info!("shutdown signal received");
        })
        .await?;

    Ok(())
}
