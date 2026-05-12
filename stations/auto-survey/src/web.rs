//! HTTP routes — axum port of Python `web.py` (FastAPI 571 lines).
//! Phase 3b: full endpoint migration.
//!
//! Uses dynamic `sqlx::query()` instead of `sqlx::query_as!()` macros to avoid
//! requiring a live DATABASE_URL at compile time.

use axum::{
    extract::{Multipart, Path, Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response, Sse},
    routing::{delete, get, post, put},
    Json, Router,
};
use chrono::{Local, NaiveDate, Timelike, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::{Row, SqlitePool};
use std::{collections::HashMap, convert::Infallible, sync::OnceLock, time::Duration};
use tokio_stream::wrappers::ReceiverStream;
use tower_http::{cors::CorsLayer, services::ServeDir};
use uuid::Uuid;

use crate::config::Settings;

// ── AppState ──────────────────────────────────────────────

#[derive(Clone)]
pub struct AppState {
    pub pool: SqlitePool,
    pub cfg: Settings,
}

// ── Error type ────────────────────────────────────────────

#[derive(Debug)]
pub struct AppError {
    status: StatusCode,
    message: String,
}

impl AppError {
    pub fn bad_request(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::BAD_REQUEST, message: msg.into() }
    }
    pub fn not_found(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::NOT_FOUND, message: msg.into() }
    }
    pub fn conflict(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::CONFLICT, message: msg.into() }
    }
    pub fn internal(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::INTERNAL_SERVER_ERROR, message: msg.into() }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let code = self.status.as_u16();
        let body = json!({"error": self.message, "code": code});
        (self.status, Json(body)).into_response()
    }
}

// Convert sqlx errors automatically
impl From<sqlx::Error> for AppError {
    fn from(e: sqlx::Error) -> Self {
        Self::internal(e.to_string())
    }
}

type ApiResult<T> = Result<T, AppError>;

// ── Request/Response schemas ──────────────────────────────

#[derive(Debug, Deserialize)]
pub struct PersonCreate {
    pub name: String,
    pub email: String,
    pub company: String,
    #[serde(default = "bool_true")]
    pub active: bool,
}

#[derive(Debug, Deserialize)]
pub struct PersonUpdate {
    pub name: Option<String>,
    pub email: Option<String>,
    pub company: Option<String>,
    pub active: Option<bool>,
}

#[derive(Debug, Deserialize)]
pub struct RunRequest {
    pub attend_url: Option<String>,
    pub quiz_url: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
pub struct PersonOut {
    pub id: String,
    pub name: String,
    pub email: String,
    pub company: String,
    pub active: bool,
    pub created_at: String,
}

#[derive(Debug, Serialize, Clone)]
pub struct DailyRunOut {
    pub id: String,
    pub run_date: String,
    pub attend_url: Option<String>,
    pub quiz_url: Option<String>,
    pub status: String,
    pub result_summary: Option<String>,
    pub created_at: String,
}

#[derive(Debug, Serialize)]
pub struct SubmissionOut {
    pub id: String,
    pub person_name: String,
    pub survey_title: String,
    pub survey_type: String,
    pub status: String,
    pub score: Option<i64>,
    pub answers_snapshot: Option<Value>,
    pub submitted_at: String,
}

#[derive(Debug, Deserialize)]
pub struct CalendarQuery {
    pub year: i32,
    pub month: u32,
}

#[derive(Debug, Deserialize)]
struct CsvPersonRow {
    name: String,
    email: String,
    company: String,
}

fn bool_true() -> bool {
    true
}

// ── Helpers ───────────────────────────────────────────────

fn new_id() -> String {
    Uuid::new_v4().to_string()
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn today_str() -> String {
    Local::now().format("%Y-%m-%d").to_string()
}

fn current_hour() -> u32 {
    Local::now().hour()
}

// Convert sqlx row → PersonOut
fn row_to_person(row: &sqlx::sqlite::SqliteRow) -> PersonOut {
    let active_i: i64 = row.get("active");
    PersonOut {
        id: row.get("id"),
        name: row.get("name"),
        email: row.get("email"),
        company: row.get("company"),
        active: active_i != 0,
        created_at: row.get("created_at"),
    }
}

// Convert sqlx row → DailyRunOut
fn row_to_run(row: &sqlx::sqlite::SqliteRow) -> DailyRunOut {
    DailyRunOut {
        id: row.get("id"),
        run_date: row.get("run_date"),
        attend_url: row.get("attend_url"),
        quiz_url: row.get("quiz_url"),
        status: row.get("status"),
        result_summary: row.get("result_summary"),
        created_at: row.get("created_at"),
    }
}

// ── Routes builder ────────────────────────────────────────

/// Resolve the static asset directory at runtime.
///
/// Priority:
/// 1. `AUTO_SURVEY_STATIC_DIR` env var (explicit override)
/// 2. `<cwd>/static` — launchd plist sets WorkingDirectory to the station root
/// 3. Walk up from the binary path looking for a `static/` sibling
/// 4. Compile-time `CARGO_MANIFEST_DIR/static` (dev / fallback)
///
/// Why: `env!("CARGO_MANIFEST_DIR")` bakes the build-time path into the binary;
/// when built inside a worktree that gets pruned post-merge, the runtime path
/// no longer exists and `index.html` 404s.
fn resolve_static_dir() -> std::path::PathBuf {
    let has_index = |p: &std::path::Path| p.join("index.html").is_file();

    if let Ok(env_dir) = std::env::var("AUTO_SURVEY_STATIC_DIR") {
        let pb = std::path::PathBuf::from(env_dir);
        if has_index(&pb) {
            return pb;
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        let pb = cwd.join("static");
        if has_index(&pb) {
            return pb;
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        let mut cursor = exe.parent().map(|p| p.to_path_buf());
        while let Some(dir) = cursor {
            let candidate = dir.join("static");
            if has_index(&candidate) {
                return candidate;
            }
            cursor = dir.parent().map(|p| p.to_path_buf());
        }
    }

    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("static")
}

fn static_dir() -> &'static std::path::Path {
    static STATIC_DIR: OnceLock<std::path::PathBuf> = OnceLock::new();
    STATIC_DIR.get_or_init(resolve_static_dir).as_path()
}

pub fn routes() -> Router<AppState> {
    let static_dir = static_dir().to_path_buf();

    Router::new()
        // People CRUD
        .route("/api/people", get(list_people).post(create_person))
        .route("/api/people/import", post(import_people_csv))
        .route(
            "/api/people/:person_id",
            put(update_person).delete(delete_person),
        )
        // Runs
        .route("/api/runs/today", get(get_today_run))
        .route("/api/runs", get(list_runs).post(create_run))
        .route("/api/runs/:run_id/events", get(run_events_stream))
        // History
        .route("/api/history", get(list_history))
        // Calendar / day detail
        .route("/api/calendar", get(get_calendar))
        .route("/api/day/:run_date", get(get_day_detail))
        // Static files: /static/*
        .nest_service("/static", ServeDir::new(&static_dir))
        // sw.js served at root (no /static/ prefix, same as Python)
        .route("/sw.js", get(serve_sw_js))
        // index.html for SPA root
        .route("/", get(serve_index))
        // CORS permissive — matches Python FastAPI default (no special config in web.py)
        .layer(CorsLayer::permissive())
}

// ── Frontend file handlers ─────────────────────────────────

async fn serve_index() -> impl IntoResponse {
    let path = static_dir().join("index.html");
    match tokio::fs::read(&path).await {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::NOT_FOUND, "index.html not found").into_response(),
    }
}

async fn serve_sw_js() -> impl IntoResponse {
    let path = static_dir().join("sw.js");
    match tokio::fs::read(&path).await {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/javascript")],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::NOT_FOUND, "sw.js not found").into_response(),
    }
}

// ── People API ────────────────────────────────────────────

/// GET /api/people
async fn list_people(State(s): State<AppState>) -> ApiResult<Json<Vec<PersonOut>>> {
    let rows = sqlx::query(
        "SELECT id, name, email, company, active, created_at FROM people ORDER BY name",
    )
    .fetch_all(&s.pool)
    .await?;

    Ok(Json(rows.iter().map(row_to_person).collect()))
}

/// POST /api/people
async fn create_person(
    State(s): State<AppState>,
    Json(data): Json<PersonCreate>,
) -> ApiResult<(StatusCode, Json<PersonOut>)> {
    let cnt: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM people WHERE email = ?")
        .bind(&data.email)
        .fetch_one(&s.pool)
        .await?;

    if cnt > 0 {
        return Err(AppError::bad_request(format!(
            "Email already exists: {}",
            data.email
        )));
    }

    let id = new_id();
    let now = now_iso();
    let active_i: i64 = if data.active { 1 } else { 0 };

    sqlx::query(
        "INSERT INTO people (id, name, email, company, active, created_at) VALUES (?,?,?,?,?,?)",
    )
    .bind(&id)
    .bind(&data.name)
    .bind(&data.email)
    .bind(&data.company)
    .bind(active_i)
    .bind(&now)
    .execute(&s.pool)
    .await?;

    let row = sqlx::query(
        "SELECT id, name, email, company, active, created_at FROM people WHERE id = ?",
    )
    .bind(&id)
    .fetch_one(&s.pool)
    .await?;

    Ok((StatusCode::CREATED, Json(row_to_person(&row))))
}

/// PUT /api/people/:person_id
async fn update_person(
    State(s): State<AppState>,
    Path(person_id): Path<String>,
    Json(data): Json<PersonUpdate>,
) -> ApiResult<Json<PersonOut>> {
    let existing = sqlx::query(
        "SELECT id, name, email, company, active, created_at FROM people WHERE id = ?",
    )
    .bind(&person_id)
    .fetch_optional(&s.pool)
    .await?
    .ok_or_else(|| AppError::not_found("Person not found"))?;

    let new_name: String = data
        .name
        .clone()
        .unwrap_or_else(|| existing.get("name"));
    let new_email: String = data
        .email
        .clone()
        .unwrap_or_else(|| existing.get("email"));
    let new_company: String = data
        .company
        .clone()
        .unwrap_or_else(|| existing.get("company"));
    let old_active: i64 = existing.get("active");
    let new_active: i64 = data
        .active
        .map(|a| if a { 1 } else { 0 })
        .unwrap_or(old_active);

    sqlx::query("UPDATE people SET name=?, email=?, company=?, active=? WHERE id=?")
        .bind(&new_name)
        .bind(&new_email)
        .bind(&new_company)
        .bind(new_active)
        .bind(&person_id)
        .execute(&s.pool)
        .await?;

    let row = sqlx::query(
        "SELECT id, name, email, company, active, created_at FROM people WHERE id = ?",
    )
    .bind(&person_id)
    .fetch_one(&s.pool)
    .await?;

    Ok(Json(row_to_person(&row)))
}

/// DELETE /api/people/:person_id
async fn delete_person(
    State(s): State<AppState>,
    Path(person_id): Path<String>,
) -> ApiResult<Json<Value>> {
    let res = sqlx::query("DELETE FROM people WHERE id = ?")
        .bind(&person_id)
        .execute(&s.pool)
        .await?;

    if res.rows_affected() == 0 {
        return Err(AppError::not_found("Person not found"));
    }
    Ok(Json(json!({"ok": true})))
}

/// POST /api/people/import — multipart CSV file upload
/// CSV format: name,email,company  (header row required)
async fn import_people_csv(
    State(s): State<AppState>,
    mut multipart: Multipart,
) -> ApiResult<Json<Value>> {
    let mut csv_bytes: Option<Vec<u8>> = None;

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::bad_request(e.to_string()))?
    {
        let bytes = field
            .bytes()
            .await
            .map_err(|e| AppError::bad_request(e.to_string()))?;
        csv_bytes = Some(bytes.to_vec());
        break;
    }

    let raw = csv_bytes.ok_or_else(|| AppError::bad_request("No file field"))?;
    let mut rdr = csv::Reader::from_reader(raw.as_slice());

    let mut imported = 0usize;
    let mut skipped = 0usize;

    for result in rdr.deserialize::<CsvPersonRow>() {
        let rec = result.map_err(|e| AppError::bad_request(e.to_string()))?;
        let cnt: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM people WHERE email = ?")
            .bind(&rec.email)
            .fetch_one(&s.pool)
            .await?;
        if cnt > 0 {
            skipped += 1;
            continue;
        }
        let id = new_id();
        let now = now_iso();
        sqlx::query(
            "INSERT INTO people (id, name, email, company, active, created_at) VALUES (?,?,?,?,1,?)",
        )
        .bind(&id)
        .bind(&rec.name)
        .bind(&rec.email)
        .bind(&rec.company)
        .bind(&now)
        .execute(&s.pool)
        .await?;
        imported += 1;
    }

    Ok(Json(json!({"imported": imported, "skipped": skipped})))
}

// ── Runs API ──────────────────────────────────────────────

/// GET /api/runs/today
async fn get_today_run(State(s): State<AppState>) -> ApiResult<Json<Option<DailyRunOut>>> {
    let today = today_str();
    let row = sqlx::query(
        "SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
         FROM daily_runs WHERE run_date = ?",
    )
    .bind(&today)
    .fetch_optional(&s.pool)
    .await?;

    Ok(Json(row.as_ref().map(row_to_run)))
}

/// GET /api/runs
async fn list_runs(State(s): State<AppState>) -> ApiResult<Json<Vec<DailyRunOut>>> {
    let rows = sqlx::query(
        "SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
         FROM daily_runs ORDER BY run_date DESC LIMIT 20",
    )
    .fetch_all(&s.pool)
    .await?;

    Ok(Json(rows.iter().map(row_to_run).collect()))
}

/// POST /api/runs
async fn create_run(
    State(s): State<AppState>,
    Json(data): Json<RunRequest>,
) -> ApiResult<(StatusCode, Json<DailyRunOut>)> {
    if data.attend_url.is_none() && data.quiz_url.is_none() {
        return Err(AppError::bad_request("Provide at least one URL"));
    }

    let today = today_str();
    let existing = sqlx::query(
        "SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
         FROM daily_runs WHERE run_date = ?",
    )
    .bind(&today)
    .fetch_optional(&s.pool)
    .await?;

    if let Some(ref ex) = existing {
        let st: String = ex.get("status");
        if matches!(st.as_str(), "running" | "completed" | "scheduled") {
            return Err(AppError::conflict(format!("Today's run already {}", st)));
        }
    }

    let new_status = if current_hour() < s.cfg.execution_hour {
        "scheduled"
    } else {
        "running"
    };
    let now = now_iso();

    let run_id: String = if let Some(ref ex) = existing {
        let id: String = ex.get("id");
        // Wipe prior result_summary so the frontend never shows a stale
        // error from a previous failed attempt while the new run is pending.
        sqlx::query(
            "UPDATE daily_runs SET attend_url=?, quiz_url=?, status=?, result_summary=NULL, updated_at=? WHERE id=?",
        )
        .bind(&data.attend_url)
        .bind(&data.quiz_url)
        .bind(new_status)
        .bind(&now)
        .bind(&id)
        .execute(&s.pool)
        .await?;
        id
    } else {
        let id = new_id();
        sqlx::query(
            "INSERT INTO daily_runs (id, run_date, attend_url, quiz_url, status, created_at, updated_at)
             VALUES (?,?,?,?,?,?,?)",
        )
        .bind(&id)
        .bind(&today)
        .bind(&data.attend_url)
        .bind(&data.quiz_url)
        .bind(new_status)
        .bind(&now)
        .bind(&now)
        .execute(&s.pool)
        .await?;
        id
    };

    if new_status == "running" {
        let pool_clone = s.pool.clone();
        let cfg_clone = s.cfg.clone();
        let rid = run_id.clone();
        let attend = data.attend_url.clone();
        let quiz = data.quiz_url.clone();
        tokio::spawn(async move {
            execute_pipeline_bg(pool_clone, cfg_clone, rid, attend, quiz).await;
        });
    }

    let row = sqlx::query(
        "SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
         FROM daily_runs WHERE id = ?",
    )
    .bind(&run_id)
    .fetch_one(&s.pool)
    .await?;

    Ok((StatusCode::CREATED, Json(row_to_run(&row))))
}

/// Background pipeline runner — wires web endpoint → orchestrator → notify.
async fn execute_pipeline_bg(
    pool: SqlitePool,
    cfg: Settings,
    run_id: String,
    attend_url: Option<String>,
    quiz_url: Option<String>,
) {
    // Format mirrors Python `auto_survey/web.py::_execute_pipeline_bg`:
    //   success → "attendance: OK" / "quiz: OK"
    //   failure → "attendance: FAILED (<err>)" / "quiz: FAILED (<err>)"
    let mut results: Vec<String> = Vec::new();
    let mut any_failed = false;

    if let Some(url) = &attend_url {
        match crate::orchestrator::run_attendance(&pool, &cfg, url, false).await {
            Ok(()) => results.push("attendance: OK".to_string()),
            Err(e) => {
                tracing::error!("run_attendance failed: {e:?}");
                results.push(format!("attendance: FAILED ({})", e));
                any_failed = true;
            }
        }
    }
    if let Some(url) = &quiz_url {
        match crate::orchestrator::run_quiz(&pool, &cfg, url, false).await {
            Ok(()) => results.push("quiz: OK".to_string()),
            Err(e) => {
                tracing::error!("run_quiz failed: {e:?}");
                results.push(format!("quiz: FAILED ({})", e));
                any_failed = true;
            }
        }
    }

    let summary = results.join(" | ");
    let now = now_iso();
    let final_status = if any_failed { "failed" } else { "completed" };
    let _ = sqlx::query(
        "UPDATE daily_runs SET status=?, result_summary=?, updated_at=? WHERE id=?",
    )
    .bind(final_status)
    .bind(&summary)
    .bind(&now)
    .bind(&run_id)
    .execute(&pool)
    .await;

    // Bark body mirrors Python: `"{marker} {summary}"` with marker = "!" on
    // any failure, "OK" on full success. Title is plain "Auto Survey".
    let client = reqwest::Client::new();
    let status_marker = if any_failed { "!" } else { "OK" };
    let body = format!("{status_marker} {summary}");
    let _ = crate::notify::send_bark(&client, &cfg, "Auto Survey", &body).await;
}

// ── SSE stream ────────────────────────────────────────────

/// GET /api/runs/:run_id/events — Server-Sent Events, push updates until done/failed
async fn run_events_stream(
    State(s): State<AppState>,
    Path(run_id): Path<String>,
) -> Sse<impl futures_core::Stream<Item = Result<axum::response::sse::Event, Infallible>>> {
    let (tx, rx) =
        tokio::sync::mpsc::channel::<Result<axum::response::sse::Event, Infallible>>(32);

    tokio::spawn(async move {
        let mut last_snapshot: Option<String> = None;

        loop {
            let run_row = sqlx::query(
                "SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
                 FROM daily_runs WHERE id = ?",
            )
            .bind(&run_id)
            .fetch_optional(&s.pool)
            .await;

            match run_row {
                Err(_) | Ok(None) => {
                    let ev = axum::response::sse::Event::default()
                        .event("error")
                        .data(r#"{"message":"Run not found"}"#);
                    let _ = tx.send(Ok(ev)).await;
                    break;
                }
                Ok(Some(run)) => {
                    let run_date: String = run.get("run_date");
                    let status: String = run.get("status");

                    let data = build_day_data(&s.pool, &run_date).await;
                    let snapshot = serde_json::to_string(&data).unwrap_or_default();

                    if Some(&snapshot) != last_snapshot.as_ref() {
                        let ev =
                            axum::response::sse::Event::default().data(snapshot.clone());
                        if tx.send(Ok(ev)).await.is_err() {
                            break;
                        }
                        last_snapshot = Some(snapshot);
                    }

                    if matches!(status.as_str(), "completed" | "failed") {
                        let done_ev = axum::response::sse::Event::default()
                            .event("done")
                            .data(format!(r#"{{"status":"{}"}}"#, status));
                        let _ = tx.send(Ok(done_ev)).await;
                        break;
                    }
                }
            }

            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    });

    Sse::new(ReceiverStream::new(rx)).keep_alive(
        axum::response::sse::KeepAlive::new().interval(Duration::from_secs(15)),
    )
}

// ── History API ───────────────────────────────────────────

/// GET /api/history
async fn list_history(State(s): State<AppState>) -> ApiResult<Json<Vec<SubmissionOut>>> {
    let rows = sqlx::query(
        r#"SELECT
               sub.id,
               sub.status,
               sub.score,
               sub.answers_snapshot,
               sub.submitted_at,
               p.name AS person_name,
               COALESCE(sv.title, sv.url) AS survey_title,
               sv.type AS survey_type
           FROM submissions sub
           JOIN surveys sv ON sv.id = sub.survey_id
           JOIN people p ON p.id = sub.person_id
           ORDER BY sub.submitted_at DESC
           LIMIT 100"#,
    )
    .fetch_all(&s.pool)
    .await?;

    let out: Vec<SubmissionOut> = rows
        .iter()
        .map(|r| {
            let title: String = r.get("survey_title");
            let title_short: String = title.chars().take(40).collect();
            let answers: Option<Value> = r
                .try_get::<Option<String>, _>("answers_snapshot")
                .ok()
                .flatten()
                .and_then(|s| serde_json::from_str(&s).ok());
            SubmissionOut {
                id: r.get("id"),
                person_name: r.get("person_name"),
                survey_title: title_short,
                survey_type: r.get("survey_type"),
                status: r.get("status"),
                score: r.try_get("score").ok(),
                answers_snapshot: answers,
                submitted_at: r.get("submitted_at"),
            }
        })
        .collect();

    Ok(Json(out))
}

// ── Calendar API ──────────────────────────────────────────

/// GET /api/calendar?year=2026&month=4
async fn get_calendar(
    State(s): State<AppState>,
    Query(q): Query<CalendarQuery>,
) -> ApiResult<Json<Vec<Value>>> {
    let start = NaiveDate::from_ymd_opt(q.year, q.month, 1)
        .ok_or_else(|| AppError::bad_request("Invalid year/month"))?;
    let (ey, em) = if q.month == 12 {
        (q.year + 1, 1u32)
    } else {
        (q.year, q.month + 1)
    };
    let end = NaiveDate::from_ymd_opt(ey, em, 1)
        .ok_or_else(|| AppError::bad_request("Invalid year/month"))?;

    let start_str = start.format("%Y-%m-%d").to_string();
    let end_str = end.format("%Y-%m-%d").to_string();

    let rows = sqlx::query(
        "SELECT run_date, status FROM daily_runs WHERE run_date >= ? AND run_date < ?",
    )
    .bind(&start_str)
    .bind(&end_str)
    .fetch_all(&s.pool)
    .await?;

    let result: Vec<Value> = rows
        .iter()
        .map(|r| {
            let d: String = r.get("run_date");
            let st: String = r.get("status");
            json!({"date": d, "status": st})
        })
        .collect();

    Ok(Json(result))
}

/// GET /api/day/:run_date
async fn get_day_detail(
    State(s): State<AppState>,
    Path(run_date): Path<String>,
) -> ApiResult<Json<Value>> {
    NaiveDate::parse_from_str(&run_date, "%Y-%m-%d")
        .map_err(|_| AppError::bad_request("Invalid date format. Use YYYY-MM-DD"))?;

    let data = build_day_data(&s.pool, &run_date).await;
    Ok(Json(data))
}

// ── Shared day-data builder ───────────────────────────────

/// Build the payload for a given run_date (shared by /api/day and SSE).
/// Mirrors Python `_build_day_data`.
async fn build_day_data(pool: &SqlitePool, run_date: &str) -> Value {
    // Fetch run row
    let run_val: Value = match sqlx::query(
        "SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
         FROM daily_runs WHERE run_date = ?",
    )
    .bind(run_date)
    .fetch_optional(pool)
    .await
    {
        Ok(Some(r)) => serde_json::to_value(row_to_run(&r)).unwrap_or(Value::Null),
        _ => Value::Null,
    };

    // Submissions for this date
    let subs = sqlx::query(
        r#"SELECT sub.id, sub.survey_id, sub.status, sub.score, sub.is_pathfinder,
                  sub.answers_snapshot, p.name AS person_name, sv.type AS survey_type
           FROM submissions sub
           JOIN people p ON p.id = sub.person_id
           JOIN surveys sv ON sv.id = sub.survey_id
           WHERE date(sub.submitted_at) = ?
           ORDER BY p.name"#,
    )
    .bind(run_date)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Unique survey IDs
    let mut survey_ids: Vec<String> = subs
        .iter()
        .map(|r| {
            let s: String = r.get("survey_id");
            s
        })
        .collect();
    survey_ids.sort();
    survey_ids.dedup();

    // Questions for these surveys
    let mut questions_out: Vec<Value> = Vec::new();
    for sid in &survey_ids {
        let qs = sqlx::query(
            "SELECT id, subject_id, question_text, options, correct_answer, verified
             FROM questions WHERE survey_id = ? ORDER BY subject_id",
        )
        .bind(sid)
        .fetch_all(pool)
        .await
        .unwrap_or_default();

        for q in &qs {
            let opts_str: String = q.get("options");
            let opts: Value =
                serde_json::from_str(&opts_str).unwrap_or(Value::Array(vec![]));
            let verified_i: i64 = q.get("verified");
            questions_out.push(json!({
                "id": q.get::<String, _>("id"),
                "subject_id": q.get::<String, _>("subject_id"),
                "question_text": q.get::<String, _>("question_text"),
                "options": opts,
                "correct_answer": q.get::<Option<String>, _>("correct_answer"),
                "verified": verified_i != 0,
            }));
        }
    }

    // Group submissions by person
    let mut person_map: HashMap<String, Value> = HashMap::new();
    for sub in &subs {
        let name: String = sub.get("person_name");
        let entry = person_map.entry(name.clone()).or_insert_with(|| {
            json!({
                "person_name": name,
                "attendance": null,
                "quiz": null,
                "score": null,
                "is_pathfinder": false,
                "answers_snapshot": null,
            })
        });

        let stype: String = sub.get("survey_type");
        let status: String = sub.get("status");
        let score: Option<i64> = sub.try_get("score").ok().flatten();
        let is_pf: i64 = sub.get("is_pathfinder");
        let snap_raw: Option<String> =
            sub.try_get("answers_snapshot").ok().flatten();

        if stype == "attendance" {
            entry["attendance"] = json!(status);
        } else if stype == "quiz" {
            entry["quiz"] = json!(status);
            entry["score"] = json!(score);
            if is_pf != 0 {
                entry["is_pathfinder"] = json!(true);
            }
            if let Some(snap) = snap_raw {
                if let Ok(v) = serde_json::from_str::<Value>(&snap) {
                    entry["answers_snapshot"] = v;
                }
            }
        }
    }

    json!({
        "run": run_val,
        "submissions": person_map.values().cloned().collect::<Vec<_>>(),
        "questions": questions_out,
    })
}
