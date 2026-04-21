mod config;
mod error;
mod health_check;
mod routes;
mod state;

use clap::Parser;
use std::net::SocketAddr;
use std::path::PathBuf;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(
    name = "remote-node-rs",
    about = "Proxy station forwarding requests to Windows GPU server"
)]
struct Cli {
    #[arg(long, default_value = "config.yaml")]
    config: PathBuf,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cli = Cli::parse();
    let cfg = config::Config::load(&cli.config)?;
    tracing::info!(
        port = cfg.port,
        remote = %cfg.remote_url,
        "remote-node-rs starting"
    );

    let state = state::AppState::new(cfg.clone())?;
    let health_state = state.clone();
    tokio::spawn(async move { health_check::run(health_state).await });

    let app = routes::router(state);

    let addr: SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!(%addr, "listening");
    axum::serve(listener, app).await?;
    Ok(())
}
