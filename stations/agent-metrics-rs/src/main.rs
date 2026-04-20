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
    /// Force a single quota refresh (bypass loop) and print formatted output.
    QuotaRefresh,
    /// One-shot scrape of LLM provider billing pages (camoufox-cli).
    /// Cronicle invokes this — replaces ws_provider_balance_sync.py.
    ProviderBalanceSync,
    /// One-shot scrape of DashScope (Qwen) free-quota dashboard.
    /// Cronicle invokes this — replaces ws_dashscope_quota_sync.py.
    DashscopeQuotaSync,
    /// Weekly model-catalog sync — scrapes 4 leaderboards via camoufox-cli,
    /// merges by Borda count, writes Redis. Replaces ws_model_catalog_sync.py.
    ModelCatalogSync,
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
        Cmd::ProviderBalanceSync => {
            let n =
                agent_metrics_rs::collectors::provider_balance::run_once(&cfg.redis_url).await?;
            // Exit non-zero if nothing succeeded (matches Python behavior).
            if n == 0 {
                anyhow::bail!("provider-balance-sync: 0 providers ok");
            }
            Ok(())
        }
        Cmd::DashscopeQuotaSync => {
            let ok =
                agent_metrics_rs::collectors::dashscope_quota::run_once(&cfg.redis_url).await?;
            if !ok {
                anyhow::bail!("dashscope-quota-sync: scrape or parse failed");
            }
            Ok(())
        }
        Cmd::ModelCatalogSync => {
            let ok =
                agent_metrics_rs::collectors::model_catalog::run_once(&cfg.redis_url).await?;
            if !ok {
                anyhow::bail!("model-catalog-sync: scrape, merge, or store failed");
            }
            Ok(())
        }
        Cmd::QuotaRefresh => {
            let (raw_cc, raw_cx, raw_gm) =
                agent_metrics_rs::collectors::quota_writer::raw_dump(&cfg).await;
            eprintln!("=== raw cc ===\n{}", serde_json::to_string_pretty(&raw_cc)?);
            eprintln!("=== raw cx ===\n{}", serde_json::to_string_pretty(&raw_cx)?);
            eprintln!("=== raw gm ===\n{}", serde_json::to_string_pretty(&raw_gm)?);
            let r = agent_metrics_rs::collectors::quota_writer::refresh_once(&cfg).await?;
            println!("{}", serde_json::to_string_pretty(&r)?);
            Ok(())
        }
        Cmd::Serve => {
            let pool = agent_metrics_rs::db::init_pool(&cfg.sqlite_path).await?;
            agent_metrics_rs::db::run_migrations(&pool).await?;
            let loop_state = agent_metrics_rs::loops::LoopState::new(cfg.sysmon_history_size);
            let session_store = agent_metrics_rs::session::SessionStore::default();

            // Track background tasks so we can flush + abort cleanly on Ctrl+C.
            let sysmon_handle = {
                let s = loop_state.clone();
                let c = cfg.clone();
                let p = pool.clone();
                tokio::spawn(async move {
                    if let Err(e) = agent_metrics_rs::loops::run_sysmon_loop(s, c, p).await {
                        tracing::error!(error = %e, "sysmon_loop_exited");
                    }
                })
            };
            let aggregator_handle = {
                let store = session_store.clone();
                let p = pool.clone();
                let c = cfg.clone();
                tokio::spawn(async move {
                    if let Err(e) = agent_metrics_rs::aggregator::run_aggregator(store, p, c).await {
                        tracing::error!(error = %e, "aggregator_exited");
                    }
                })
            };
            // Quota writer background loop — replaces Python `quota_sidecar.py`.
            let quota_handle = {
                let c = cfg.clone();
                tokio::spawn(async move {
                    if let Err(e) =
                        agent_metrics_rs::collectors::quota_writer::run_quota_loop(c, 60).await
                    {
                        tracing::error!(error = %e, "quota_writer_exited");
                    }
                })
            };

            let app_state = agent_metrics_rs::web::AppState {
                settings: std::sync::Arc::new(cfg.clone()),
                pool: pool.clone(),
                loop_state,
                session_store: session_store.clone(),
            };
            let app = agent_metrics_rs::web::build_router(app_state);

            let addr: std::net::SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
            tracing::info!(%addr, "agent-metrics-rs serving");
            let listener = tokio::net::TcpListener::bind(addr).await?;

            let shutdown = async {
                let _ = tokio::signal::ctrl_c().await;
                tracing::info!("shutdown signal received");
            };
            axum::serve(listener, app)
                .with_graceful_shutdown(shutdown)
                .await?;

            // Final flush of pending session snapshots before exit
            tracing::info!("flushing pending snapshots before exit");
            let pending = session_store.collect_pending_snapshots().await;
            if !pending.is_empty() {
                if let Err(e) = agent_metrics_rs::aggregator::final_flush(&pool, &pending).await {
                    tracing::error!(error = %e, "final_flush_failed");
                } else {
                    tracing::info!(count = pending.len(), "final_flush_done");
                }
            }

            // Abort background tasks (we already drained pending snapshots)
            sysmon_handle.abort();
            aggregator_handle.abort();
            quota_handle.abort();
            let _ = sysmon_handle.await;
            let _ = aggregator_handle.await;
            let _ = quota_handle.await;

            pool.close().await;
            tracing::info!("agent-metrics-rs stopped cleanly");
            Ok(())
        }
    }
}
