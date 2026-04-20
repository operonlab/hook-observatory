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
    /// Probe LiteLLM proxy /health + /model/info; print JSON.
    LitellmStatus,
    /// Print get_litellm_manual_summary as JSON (provider quotas + dashscope).
    LitellmSummary,
    /// Print month-to-date usage (Claude + LiteLLM) as JSON.
    UsageMtd,
    /// Print model breakdown (claude_models + litellm_models) as JSON.
    UsageByModel {
        #[arg(long, default_value_t = 30)]
        days: i64,
    },
    /// Print today's Claude cost as JSON.
    UsageToday,
    /// Print quota formatted snapshot read from Redis.
    QuotaCurrent,
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
        Cmd::LitellmStatus => {
            let r = agent_metrics_rs::collectors::litellm::get_litellm_status(&cfg).await;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        Cmd::LitellmSummary => {
            let r = agent_metrics_rs::collectors::litellm::get_litellm_manual_summary(&cfg).await;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        Cmd::UsageMtd => {
            let r = agent_metrics_rs::collectors::usage::get_month_to_date(&cfg).await;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        Cmd::UsageByModel { days } => {
            let r = agent_metrics_rs::collectors::usage::get_model_breakdown(&cfg, days).await;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        Cmd::UsageToday => {
            let r = agent_metrics_rs::collectors::usage::get_today_cost(&cfg).await;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        Cmd::QuotaCurrent => {
            let r = agent_metrics_rs::collectors::quota::get_quota(&cfg).await;
            println!("{}", serde_json::to_string(&r)?);
            Ok(())
        }
        Cmd::Serve => {
            let pool = agent_metrics_rs::db::init_pool(&cfg.sqlite_path).await?;
            agent_metrics_rs::db::run_migrations(&pool).await?;
            let loop_state = agent_metrics_rs::loops::LoopState::new(cfg.sysmon_history_size);

            // Spawn the sysmon background loop
            let bg_state = loop_state.clone();
            let bg_cfg = cfg.clone();
            let bg_pool = pool.clone();
            tokio::spawn(async move {
                if let Err(e) = agent_metrics_rs::loops::run_sysmon_loop(bg_state, bg_cfg, bg_pool).await {
                    tracing::error!(error = %e, "sysmon_loop_exited");
                }
            });

            let app_state = agent_metrics_rs::web::AppState {
                settings: std::sync::Arc::new(cfg.clone()),
                pool,
                loop_state,
            };
            let app = agent_metrics_rs::web::build_router(app_state);

            let addr: std::net::SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
            tracing::info!(%addr, "agent-metrics-rs serving");
            let listener = tokio::net::TcpListener::bind(addr).await?;
            axum::serve(listener, app).await?;
            Ok(())
        }
    }
}
