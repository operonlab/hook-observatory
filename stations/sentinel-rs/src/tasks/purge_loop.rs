use sqlx::SqlitePool;
use std::time::Duration;
use tokio::time::interval;
use tokio_util::sync::CancellationToken;

pub async fn run(
    pool: SqlitePool,
    interval_sec: u64,
    retention_days: i64,
    token: CancellationToken,
) {
    let mut ticker = interval(Duration::from_secs(interval_sec));
    ticker.tick().await; // skip immediate tick
    loop {
        tokio::select! {
            _ = token.cancelled() => {
                tracing::info!("purge_loop shutting down");
                return;
            }
            _ = ticker.tick() => {
                let cutoff = format!("-{} days", retention_days);
                match sqlx::query(
                    "DELETE FROM health_checks WHERE created_at < datetime('now', ?)"
                )
                .bind(&cutoff)
                .execute(&pool)
                .await
                {
                    Ok(r) => tracing::info!(rows = r.rows_affected(), "purge complete"),
                    Err(e) => tracing::warn!("purge failed: {}", e),
                }
            }
        }
    }
}
