//! SQLite pool init.

use anyhow::Result;
use sqlx::SqlitePool;
use std::path::Path;

pub async fn init_pool(path: &str) -> Result<SqlitePool> {
    workshop_sqlite_pool::PoolBuilder::default()
        .max_connections(8)
        .connect(Path::new(path))
        .await
}
