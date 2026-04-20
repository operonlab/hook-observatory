//! Background aggregator — periodic SQLite flush + daily rollover + retention purge.
//!
//! Mirrors `agent_metrics.aggregator`. Runs forever with a fixed cadence.

use crate::config::Settings;
use crate::session::SessionStore;
use anyhow::Result;
use sqlx::SqlitePool;
use std::time::Duration;

const FLUSH_EVERY_SECONDS: u64 = 60;
const EXPIRY_CHECK_EVERY_SECONDS: u64 = 10;
const RETENTION_SNAPSHOTS_DAYS: i64 = 30;
const RETENTION_DAILY_DAYS: i64 = 365;

pub async fn run_aggregator(store: SessionStore, pool: SqlitePool, _settings: Settings) -> Result<()> {
    tracing::info!("aggregator_started");

    let mut last_flush = std::time::Instant::now();
    let mut last_purge = std::time::Instant::now() - Duration::from_secs(3600);

    loop {
        tokio::time::sleep(Duration::from_secs(EXPIRY_CHECK_EVERY_SECONDS)).await;

        let _expired = store.expire_stale().await;

        if last_flush.elapsed() >= Duration::from_secs(FLUSH_EVERY_SECONDS) {
            last_flush = std::time::Instant::now();

            // Upsert sessions FIRST so foreign-key-style joins on snapshots
            // can resolve `session_id` → session metadata (Python aggregator
            // never wrote this table; Rust does because the route advertises
            // a DB-backed `?active_only=false` query).
            let active = store.get_active_sessions().await;
            if !active.is_empty() {
                if let Err(e) = upsert_sessions(&pool, &active).await {
                    tracing::error!(error = %e, "sessions_upsert_failed");
                } else {
                    tracing::debug!(count = active.len(), "sessions_upserted");
                }
            }

            let snaps = store.collect_pending_snapshots().await;
            if !snaps.is_empty() {
                if let Err(e) = flush_snapshots(&pool, &snaps).await {
                    tracing::error!(error = %e, "snapshots_flush_failed");
                } else {
                    tracing::info!(count = snaps.len(), "snapshots_flushed");
                }
            }

            if let Some(summary) = store.maybe_daily_rollover().await {
                if let Err(e) = upsert_daily_summary(&pool, &summary).await {
                    tracing::error!(error = %e, "daily_summary_failed");
                }
            }
        }

        if last_purge.elapsed() >= Duration::from_secs(3600) {
            last_purge = std::time::Instant::now();
            if let Err(e) = purge_old(&pool).await {
                tracing::warn!(error = %e, "retention_purge_failed");
            }
        }
    }
}

async fn flush_snapshots(pool: &SqlitePool, snaps: &[crate::session::SnapshotRow]) -> Result<()> {
    let mut tx = pool.begin().await?;
    for s in snaps {
        sqlx::query(
            "INSERT INTO snapshots (id, ts, session_id, sid, cli, cost_usd, context_used_pct, input_tokens, output_tokens) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
        )
        .bind(&s.id)
        .bind(&s.ts)
        .bind(&s.session_id)
        .bind(&s.sid)
        .bind(&s.cli)
        .bind(s.cost_usd)
        .bind(s.context_used_pct)
        .bind(s.input_tokens)
        .bind(s.output_tokens)
        .execute(&mut *tx)
        .await?;
    }
    tx.commit().await?;
    Ok(())
}

/// Public entry for the main binary's shutdown path — flush any in-memory
/// snapshots that the periodic loop hasn't drained yet.
pub async fn final_flush(
    pool: &SqlitePool,
    snaps: &[crate::session::SnapshotRow],
) -> Result<()> {
    flush_snapshots(pool, snaps).await
}

async fn upsert_sessions(
    pool: &SqlitePool,
    sessions: &[crate::session::SessionInfo],
) -> Result<()> {
    let mut tx = pool.begin().await?;
    for s in sessions {
        sqlx::query(
            "INSERT INTO sessions \
             (id, sid, cli, model_id, model_display, project, cost_usd, context_used_pct, \
              context_window_size, input_tokens, output_tokens, cache_creation_tokens, \
              cache_read_tokens, first_seen, last_seen, is_active) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16) \
             ON CONFLICT(id) DO UPDATE SET \
                cli                   = excluded.cli, \
                model_id              = excluded.model_id, \
                model_display         = excluded.model_display, \
                project               = excluded.project, \
                cost_usd              = excluded.cost_usd, \
                context_used_pct      = excluded.context_used_pct, \
                context_window_size   = excluded.context_window_size, \
                input_tokens          = excluded.input_tokens, \
                output_tokens         = excluded.output_tokens, \
                cache_creation_tokens = excluded.cache_creation_tokens, \
                cache_read_tokens     = excluded.cache_read_tokens, \
                last_seen             = excluded.last_seen, \
                is_active             = excluded.is_active",
        )
        .bind(&s.id)
        .bind(&s.sid)
        .bind(&s.cli)
        .bind(&s.model_id)
        .bind(&s.model_display)
        .bind(&s.project)
        .bind(s.cost_usd)
        .bind(s.context_used_pct)
        .bind(s.context_window_size)
        .bind(s.input_tokens)
        .bind(s.output_tokens)
        .bind(s.cache_creation_tokens)
        .bind(s.cache_read_tokens)
        .bind(&s.first_seen)
        .bind(&s.last_seen)
        .bind(if s.is_active { 1_i64 } else { 0_i64 })
        .execute(&mut *tx)
        .await?;
    }
    tx.commit().await?;
    Ok(())
}

async fn upsert_daily_summary(
    pool: &SqlitePool,
    s: &crate::session::DailySummaryRow,
) -> Result<()> {
    sqlx::query(
        "INSERT INTO daily_summary (id, date, total_cost_usd, total_sessions, peak_concurrent, \
         total_input_tokens, total_output_tokens, avg_context_pct, max_context_pct) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9) \
         ON CONFLICT(date) DO UPDATE SET \
            total_cost_usd = excluded.total_cost_usd, \
            total_sessions = excluded.total_sessions, \
            peak_concurrent = excluded.peak_concurrent, \
            total_input_tokens = excluded.total_input_tokens, \
            total_output_tokens = excluded.total_output_tokens, \
            avg_context_pct = excluded.avg_context_pct, \
            max_context_pct = excluded.max_context_pct",
    )
    .bind(&s.id)
    .bind(&s.date)
    .bind(s.total_cost_usd)
    .bind(s.total_sessions)
    .bind(s.peak_concurrent)
    .bind(s.total_input_tokens)
    .bind(s.total_output_tokens)
    .bind(s.avg_context_pct)
    .bind(s.max_context_pct)
    .execute(pool)
    .await?;
    Ok(())
}

async fn purge_old(pool: &SqlitePool) -> Result<()> {
    let snap_cutoff = (chrono::Utc::now() - chrono::Duration::days(RETENTION_SNAPSHOTS_DAYS))
        .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let daily_cutoff = (chrono::Utc::now() - chrono::Duration::days(RETENTION_DAILY_DAYS))
        .format("%Y-%m-%d")
        .to_string();
    sqlx::query("DELETE FROM snapshots WHERE ts < ?1")
        .bind(snap_cutoff)
        .execute(pool)
        .await?;
    sqlx::query("DELETE FROM daily_summary WHERE date < ?1")
        .bind(daily_cutoff)
        .execute(pool)
        .await?;
    Ok(())
}
