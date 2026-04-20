//! agent-metrics-rs binary entry.
//!
//! Subcommands:
//!   migrate           apply SQLite migrations
//!   config            print resolved Settings
//!   sysmon-once       collect a single sysmon snapshot, print JSON
//!   sysmon-loop       run the sysmon background loop (sysmon + guardian + sweep)
//!   serve             Phase 4 — placeholder

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
    /// Collect a single sysmon snapshot and print as JSON.
    SysmonOnce,
    /// Run the sysmon background loop (sysmon + guardian + sweep) until cancelled.
    SysmonLoop,
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
        Cmd::SysmonOnce => {
            // Network rates need two ticks to compute — first call seeds the
            // baseline, second call gives a real reading.
            let _seed = agent_metrics_rs::sysmon::collect_all().await;
            let snap = agent_metrics_rs::sysmon::collect_all().await;
            println!("{}", serde_json::to_string(&snap)?);
            Ok(())
        }
        Cmd::SysmonLoop => {
            let pool = agent_metrics_rs::db::init_pool(&cfg.sqlite_path).await?;
            agent_metrics_rs::db::run_migrations(&pool).await?;
            let state = agent_metrics_rs::loops::LoopState::new(cfg.sysmon_history_size);
            agent_metrics_rs::loops::run_sysmon_loop(state, cfg, pool).await
        }
        Cmd::Serve => {
            anyhow::bail!("serve command lands in Phase 4; current build is Phase 2");
        }
    }
}
