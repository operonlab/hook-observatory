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
    name = "remote-node",
    about = "Proxy station forwarding requests to Windows GPU server"
)]
struct Cli {
    #[arg(long, default_value = "config.yaml")]
    config: PathBuf,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Route logs to stderr so stdout is reserved for any future CLI output.
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cli = Cli::parse();
    let cfg = config::Config::load(&cli.config)?;
    tracing::info!(
        port = cfg.port,
        remote = %cfg.remote_url,
        "remote-node starting"
    );

    let state = state::AppState::new(cfg.clone())?;
    let health_state = state.clone();
    tokio::spawn(async move { health_check::run(health_state).await });

    let app = routes::router(state);

    let addr: SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!(%addr, "listening");
    // Graceful SIGTERM/SIGINT handling so process-manager kills produce a
    // clean exit(0) instead of an abrupt abnormal exit — matches
    // auto-survey-rs policy and avoids half-done proxy forwards in-flight.
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    Ok(())
}

async fn shutdown_signal() {
    use tokio::signal::unix::{signal, SignalKind};
    let mut term = signal(SignalKind::terminate()).expect("install SIGTERM handler");
    let mut intr = signal(SignalKind::interrupt()).expect("install SIGINT handler");
    tokio::select! {
        _ = term.recv() => tracing::info!("received SIGTERM, shutting down"),
        _ = intr.recv() => tracing::info!("received SIGINT, shutting down"),
    }
}
