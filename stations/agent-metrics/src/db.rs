//! SQLite pool init + migration runner.
//!
//! Uses the shared `workshop_sqlite_pool` baseline (WAL + NORMAL +
//! busy_timeout + autocheckpoint) so tuning stays consistent across stations.

use anyhow::Result;
use sqlx::SqlitePool;
use std::path::Path;

pub async fn init_pool(path: &str) -> Result<SqlitePool> {
    workshop_sqlite_pool::PoolBuilder::default()
        .max_connections(8)
        .connect(Path::new(path))
        .await
}

pub async fn run_migrations(pool: &SqlitePool) -> Result<()> {
    sqlx::migrate!("./migrations").run(pool).await?;
    Ok(())
}
