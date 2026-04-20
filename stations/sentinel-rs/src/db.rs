use sqlx::SqlitePool;
use std::path::Path;
use std::time::Duration;

pub async fn connect(db_path: &Path) -> anyhow::Result<SqlitePool> {
    let pool = workshop_sqlite_pool::PoolBuilder::default()
        .max_connections(5)
        .acquire_timeout(Duration::from_secs(10))
        .connect(db_path)
        .await?;

    sqlx::migrate!("./migrations").run(&pool).await?;
    Ok(pool)
}
