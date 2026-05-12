//! system-monitor-rs CLI entrypoint.
//!
//! Subcommands mirror the Python facade so Cronicle / shell scripts can drop
//! `python3 api.py` → `system-monitor-rs serve` with no other change.

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use std::net::SocketAddr;
use tracing_subscriber::EnvFilter;

use system_monitor_rs::config::Settings;
use system_monitor_rs::{api, guardian, reporter, tmux_status};

#[derive(Parser, Debug)]
#[command(
    name = "system-monitor-rs",
    version,
    about = "Workshop system-monitor — Rust rewrite (sysinfo + axum)"
)]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Start the HTTP server (default when no subcommand given).
    Serve {
        #[arg(long, default_value = "127.0.0.1")]
        host: String,
        #[arg(long, default_value_t = 10102)]
        port: u16,
    },
    /// Generate weekly or monthly LLM report (Cronicle-driven).
    Reporter {
        #[arg(long = "type", value_parser = ["weekly", "monthly"])]
        kind: String,
    },
    /// Run a single guardian tick (rule evaluation + remediation).
    GuardianTick {
        /// If set, log decisions but do NOT execute SIGTERM / AppleScript.
        #[arg(long = "dry-run")]
        dry_run: bool,
    },
    /// Print tmux status line (replaces tmux_status.py / tmux_status.sh).
    TmuxStatus {
        #[arg(default_value = "system")]
        kind: String,
    },
    /// Health-check probe (returns 0 if /health on the configured port responds).
    Healthcheck {
        #[arg(long, default_value_t = 10102)]
        port: u16,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cli = Cli::parse();
    let cmd = cli.command.unwrap_or(Command::Serve {
        host: "127.0.0.1".to_string(),
        port: 10102,
    });

    let cfg = Settings::from_env();

    match cmd {
        Command::Serve { host, port } => serve(cfg, host, port).await,
        Command::Reporter { kind } => reporter::run(&cfg, &kind).await,
        Command::GuardianTick { dry_run } => guardian::tick(&cfg, dry_run).await,
        Command::TmuxStatus { kind } => tmux_status::print(&cfg, &kind).await,
        Command::Healthcheck { port } => healthcheck(port).await,
    }
}

async fn serve(cfg: Settings, host: String, port: u16) -> Result<()> {
    tracing::info!("system-monitor-rs starting on {host}:{port}");
    let app = api::build_router(cfg).await?;
    let addr: SocketAddr = format!("{host}:{port}")
        .parse()
        .with_context(|| format!("parse bind address {host}:{port}"))?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("listening on {addr}");
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

async fn healthcheck(port: u16) -> Result<()> {
    let url = format!("http://127.0.0.1:{port}/health");
    let resp = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()?
        .get(&url)
        .send()
        .await?;
    if resp.status().is_success() {
        println!("ok");
        Ok(())
    } else {
        anyhow::bail!("healthcheck failed: HTTP {}", resp.status())
    }
}
