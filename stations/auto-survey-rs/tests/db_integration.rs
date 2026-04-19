//! Integration tests: SQLite schema + basic CRUD sanity checks.
//!
//! These tests:
//!   1. Create an in-memory SQLite DB (or file DB under target/tmp/)
//!   2. Run the migration DDL from migrations/20260419000001_init.sql
//!   3. Verify all 5 tables exist and are query-able
//!   4. Insert one sample row per table and read it back, ensuring type round-trips work
//!
//! Run with:
//!   cargo test --test db_integration
//!
//! The tests do NOT require PostgreSQL or the live data file.

use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};
use sqlx::SqlitePool;
use std::str::FromStr;

// ---------------------------------------------------------------------------
// Helper: spin up a fresh in-memory SQLite pool with schema applied.
// ---------------------------------------------------------------------------
async fn test_pool() -> SqlitePool {
    let opts = SqliteConnectOptions::from_str("sqlite::memory:")
        .expect("parse sqlite::memory: url")
        .foreign_keys(true);

    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(opts)
        .await
        .expect("open in-memory SQLite");

    // Apply migration DDL directly (sqlx::migrate! requires a file path, so we embed inline)
    let ddl = include_str!("../migrations/20260419000001_init.sql");
    sqlx::raw_sql(ddl).execute(&pool).await.expect("run DDL");

    pool
}

// ---------------------------------------------------------------------------
// 1. All 5 tables exist and COUNT(*) returns 0 on a fresh DB
// ---------------------------------------------------------------------------
#[tokio::test]
async fn test_all_tables_exist() {
    let pool = test_pool().await;

    for table in &["surveys", "questions", "people", "submissions", "daily_runs"] {
        let count: i64 = sqlx::query_scalar(&format!("SELECT COUNT(*) FROM {table}"))
            .fetch_one(&pool)
            .await
            .unwrap_or_else(|e| panic!("SELECT COUNT(*) FROM {table} failed: {e}"));
        assert_eq!(count, 0, "expected empty table: {table}");
    }
}

// ---------------------------------------------------------------------------
// 2. Insert a survey row and read it back
// ---------------------------------------------------------------------------
#[tokio::test]
async fn test_insert_and_read_survey() {
    let pool = test_pool().await;

    let id = "550e8400-e29b-41d4-a716-446655440000";
    let url = "https://www.surveycake.com/s/test123";
    let url_hash = "deadbeefdeadbeef";
    let title = "Weekly Quiz";
    let survey_type = "quiz";
    let created_at = "2026-04-19T10:30:00+00:00";

    sqlx::query(
        r#"
        INSERT INTO surveys (id, url, url_hash, title, type, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        "#,
    )
    .bind(id)
    .bind(url)
    .bind(url_hash)
    .bind(title)
    .bind(survey_type)
    .bind(created_at)
    .execute(&pool)
    .await
    .expect("insert survey");

    let row = sqlx::query_as::<_, (String, String, String, String)>(
        "SELECT id, url, type, created_at FROM surveys WHERE id = ?",
    )
    .bind(id)
    .fetch_one(&pool)
    .await
    .expect("fetch survey");

    assert_eq!(row.0, id);
    assert_eq!(row.1, url);
    assert_eq!(row.2, survey_type);
    assert_eq!(row.3, created_at);
}

// ---------------------------------------------------------------------------
// 3. Insert a submission with is_pathfinder + answers_snapshot (the two missing fields)
// ---------------------------------------------------------------------------
#[tokio::test]
async fn test_insert_submission_with_pathfinder_and_snapshot() {
    let pool = test_pool().await;

    // Need parent survey + person rows first (FK)
    let survey_id = "aaaa0000-0000-0000-0000-000000000001";
    let person_id = "bbbb0000-0000-0000-0000-000000000002";

    sqlx::query(
        "INSERT INTO surveys (id, url, url_hash, type) VALUES (?, ?, ?, ?)",
    )
    .bind(survey_id)
    .bind("https://www.surveycake.com/s/abc")
    .bind("abc_hash_001")
    .bind("attendance")
    .execute(&pool)
    .await
    .expect("insert parent survey");

    sqlx::query(
        "INSERT INTO people (id, name, email, company) VALUES (?, ?, ?, ?)",
    )
    .bind(person_id)
    .bind("Test Person")
    .bind("test@example.com")
    .bind("TestCo")
    .execute(&pool)
    .await
    .expect("insert parent person");

    let sub_id = "cccc0000-0000-0000-0000-000000000003";
    let snapshot = r#"{"subject-5":"A","subject-6":"C"}"#;

    sqlx::query(
        r#"
        INSERT INTO submissions
            (id, survey_id, person_id, status, score, is_pathfinder, answers_snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        "#,
    )
    .bind(sub_id)
    .bind(survey_id)
    .bind(person_id)
    .bind("success")
    .bind(100_i32)
    .bind(1_i32)          // is_pathfinder = true
    .bind(snapshot)
    .execute(&pool)
    .await
    .expect("insert submission");

    let row = sqlx::query_as::<_, (String, i32, i32, String)>(
        "SELECT id, score, is_pathfinder, answers_snapshot FROM submissions WHERE id = ?",
    )
    .bind(sub_id)
    .fetch_one(&pool)
    .await
    .expect("fetch submission");

    assert_eq!(row.0, sub_id);
    assert_eq!(row.1, 100);
    assert_eq!(row.2, 1, "is_pathfinder should be 1 (true)");

    // Parse answers_snapshot back to JSON
    let parsed: serde_json::Value =
        serde_json::from_str(&row.3).expect("answers_snapshot must be valid JSON");
    assert_eq!(parsed["subject-5"], "A");
    assert_eq!(parsed["subject-6"], "C");
}

// ---------------------------------------------------------------------------
// 4. Insert a daily_run row
// ---------------------------------------------------------------------------
#[tokio::test]
async fn test_insert_daily_run() {
    let pool = test_pool().await;

    let id = "dddd0000-0000-0000-0000-000000000004";
    sqlx::query(
        r#"
        INSERT INTO daily_runs (id, run_date, status)
        VALUES (?, ?, ?)
        "#,
    )
    .bind(id)
    .bind("2026-04-19")
    .bind("pending")
    .execute(&pool)
    .await
    .expect("insert daily_run");

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM daily_runs")
        .fetch_one(&pool)
        .await
        .expect("count daily_runs");
    assert_eq!(count, 1);
}

// ---------------------------------------------------------------------------
// 5. CHECK constraint: invalid status value is rejected
// ---------------------------------------------------------------------------
#[tokio::test]
async fn test_check_constraint_status() {
    let pool = test_pool().await;

    // First insert valid survey + person
    let survey_id = "eeee0000-0000-0000-0000-000000000005";
    let person_id = "ffff0000-0000-0000-0000-000000000006";
    sqlx::query("INSERT INTO surveys (id, url, url_hash, type) VALUES (?, ?, ?, ?)")
        .bind(survey_id)
        .bind("https://www.surveycake.com/s/check")
        .bind("check_hash_001")
        .bind("quiz")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO people (id, name, email, company) VALUES (?, ?, ?, ?)")
        .bind(person_id)
        .bind("Check Person")
        .bind("check@example.com")
        .bind("CheckCo")
        .execute(&pool)
        .await
        .unwrap();

    let result = sqlx::query(
        "INSERT INTO submissions (id, survey_id, person_id, status) VALUES (?, ?, ?, ?)",
    )
    .bind("9999-sub")
    .bind(survey_id)
    .bind(person_id)
    .bind("invalid_status")  // should violate CHECK constraint
    .execute(&pool)
    .await;

    assert!(
        result.is_err(),
        "Expected CHECK constraint violation for invalid status"
    );
}

// ---------------------------------------------------------------------------
// 6. UNIQUE constraint: duplicate survey_id+person_id rejected (uq_survey_person)
// ---------------------------------------------------------------------------
#[tokio::test]
async fn test_unique_survey_person() {
    let pool = test_pool().await;

    let survey_id = "1111aaaa-0000-0000-0000-000000000007";
    let person_id = "2222bbbb-0000-0000-0000-000000000008";

    sqlx::query("INSERT INTO surveys (id, url, url_hash, type) VALUES (?, ?, ?, ?)")
        .bind(survey_id)
        .bind("https://www.surveycake.com/s/uq")
        .bind("uq_hash_001")
        .bind("quiz")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO people (id, name, email, company) VALUES (?, ?, ?, ?)")
        .bind(person_id)
        .bind("UQ Person")
        .bind("uq@example.com")
        .bind("UQCo")
        .execute(&pool)
        .await
        .unwrap();

    let insert = |sub_id: &'static str| {
        let pool = pool.clone();
        async move {
            sqlx::query(
                "INSERT INTO submissions (id, survey_id, person_id, status) VALUES (?, ?, ?, ?)",
            )
            .bind(sub_id)
            .bind(survey_id)
            .bind(person_id)
            .bind("success")
            .execute(&pool)
            .await
        }
    };

    insert("sub-uq-001").await.expect("first insert should succeed");
    let second = insert("sub-uq-002").await;
    assert!(second.is_err(), "Expected UNIQUE constraint violation on (survey_id, person_id)");
}
