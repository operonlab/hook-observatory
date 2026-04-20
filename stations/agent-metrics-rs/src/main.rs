//! agent-metrics-rs binary entry — Phase 1 skeleton.
//!
//! Currently exposes:
//!   - `agent-metrics-rs migrate`   — open SQLite, apply migrations, exit
//!   - `agent-metrics-rs serve`     — placeholder, prints config & exits non-zero
//! Phase 2+ adds the actual loops and HTTP server.

use anyhow::Result;
use clap::{Parser, Subcommand};
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(name = "agent-metrics-rs", version)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Apply pending SQLite migrations and exit.
    Migrate,
    /// Print the resolved configuration (sanity check).
    Config,
    /// Run the API server (Phase 4 — not implemented yet).
    Serve,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cli = Cli::parse();
    let cfg = agent_metrics_rs::config::Settings::from_env();

    match cli.cmd {
        Cmd::Migrate => {
            tracing::info!(path = %cfg.sqlite_path, "running migrations");
            let pool = agent_metrics_rs::db::init_pool(&cfg.sqlite_path).await?;
            agent_metrics_rs::db::run_migrations(&pool).await?;
            tracing::info!("migrations applied");
            Ok(())
        }
        Cmd::Config => {
            println!("{:#?}", cfg);
            Ok(())
        }
        Cmd::Serve => {
            anyhow::bail!("serve command lands in Phase 4; current build is Phase 1 skeleton");
        }
    }
}
