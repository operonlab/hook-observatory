//! Workshop SQLite pool baseline.
//!
//! Every Rust station that owns a SQLite file should obtain its `SqlitePool`
//! through [`connect`] (or the [`PoolBuilder`] for non-default tuning).
//!
//! Baseline pragmas applied to every connection:
//! - `journal_mode = WAL`            — concurrent readers + single writer
//! - `synchronous = NORMAL`          — durable enough under WAL, ~2-5x faster than FULL
//! - `busy_timeout = 5000ms`         — avoid SQLITE_BUSY under contention
//! - `wal_autocheckpoint = 1000`     — flush WAL every ~1000 pages (~4MB), prevents WAL bloat
//! - `foreign_keys = ON`             — enforce FK constraints (off by default in SQLite)
//!
//! Why a shared crate: previously each station re-derived these settings, with drift
//! (e.g. `auto-survey-rs` was missing `synchronous` + `busy_timeout`). Centralising
//! prevents future regressions and keeps tuning decisions in one file.

use anyhow::{Context, Result};
use sqlx::sqlite::{
    SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
};
use sqlx::SqlitePool;
use std::path::Path;
use std::str::FromStr;
use std::time::Duration;

/// Pool tuning knobs. Defaults match the workshop baseline; override only when
/// a station has measured evidence to do so.
#[derive(Debug, Clone)]
pub struct PoolBuilder {
    pub max_connections: u32,
    pub acquire_timeout: Duration,
    pub busy_timeout: Duration,
    pub wal_autocheckpoint_pages: u32,
    pub create_if_missing: bool,
    pub foreign_keys: bool,
}

impl Default for PoolBuilder {
    fn default() -> Self {
        Self {
            max_connections: 5,
            acquire_timeout: Duration::from_secs(10),
            busy_timeout: Duration::from_secs(5),
            wal_autocheckpoint_pages: 1000,
            create_if_missing: true,
            foreign_keys: true,
        }
    }
}

impl PoolBuilder {
    pub fn max_connections(mut self, n: u32) -> Self {
        self.max_connections = n;
        self
    }

    pub fn acquire_timeout(mut self, d: Duration) -> Self {
        self.acquire_timeout = d;
        self
    }

    pub fn busy_timeout(mut self, d: Duration) -> Self {
        self.busy_timeout = d;
        self
    }

    /// Pages between auto-checkpoints. SQLite default is 1000 (~4MB at 4KB pages).
    /// Set lower for write-heavy stations to keep WAL small.
    pub fn wal_autocheckpoint_pages(mut self, n: u32) -> Self {
        self.wal_autocheckpoint_pages = n;
        self
    }

    pub fn create_if_missing(mut self, v: bool) -> Self {
        self.create_if_missing = v;
        self
    }

    pub fn foreign_keys(mut self, v: bool) -> Self {
        self.foreign_keys = v;
        self
    }

    pub async fn connect(self, db_path: &Path) -> Result<SqlitePool> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("create db parent dir: {}", parent.display()))?;
        }

        let url = format!("sqlite://{}", db_path.display());
        let opts = SqliteConnectOptions::from_str(&url)
            .with_context(|| format!("parse sqlite url: {url}"))?
            .create_if_missing(self.create_if_missing)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Normal)
            .busy_timeout(self.busy_timeout)
            .foreign_keys(self.foreign_keys)
            .pragma(
                "wal_autocheckpoint",
                self.wal_autocheckpoint_pages.to_string(),
            );

        let pool = SqlitePoolOptions::new()
            .max_connections(self.max_connections)
            .acquire_timeout(self.acquire_timeout)
            .connect_with(opts)
            .await
            .with_context(|| format!("open sqlite pool at {}", db_path.display()))?;

        tracing::info!(
            db = %db_path.display(),
            max_connections = self.max_connections,
            "sqlite pool ready (WAL+NORMAL baseline)"
        );

        Ok(pool)
    }
}

/// Open a SQLite pool at `db_path` with the workshop baseline pragmas.
/// Equivalent to `PoolBuilder::default().connect(db_path)`.
pub async fn connect(db_path: &Path) -> Result<SqlitePool> {
    PoolBuilder::default().connect(db_path).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use sqlx::Row;

    #[tokio::test]
    async fn baseline_pragmas_applied() {
        let tmp = std::env::temp_dir().join(format!(
            "ws-sqlite-pool-test-{}.db",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&tmp);

        let pool = connect(&tmp).await.expect("connect");

        let journal: String = sqlx::query("PRAGMA journal_mode")
            .fetch_one(&pool)
            .await
            .unwrap()
            .get(0);
        assert_eq!(journal.to_lowercase(), "wal");

        let sync: i64 = sqlx::query("PRAGMA synchronous")
            .fetch_one(&pool)
            .await
            .unwrap()
            .get(0);
        assert_eq!(sync, 1, "synchronous should be NORMAL (1)");

        let busy: i64 = sqlx::query("PRAGMA busy_timeout")
            .fetch_one(&pool)
            .await
            .unwrap()
            .get(0);
        assert_eq!(busy, 5000);

        let fk: i64 = sqlx::query("PRAGMA foreign_keys")
            .fetch_one(&pool)
            .await
            .unwrap()
            .get(0);
        assert_eq!(fk, 1);

        pool.close().await;
        let _ = std::fs::remove_file(&tmp);
    }
}
