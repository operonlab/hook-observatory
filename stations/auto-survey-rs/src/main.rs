//! auto-survey-rs CLI entrypoint.
//!
//! Subcommands mirror `stations/auto-survey/src/auto_survey/cli.py` 1-to-1 so
//! Cronicle runners / shell scripts can drop `uv run auto-survey X` →
//! `auto-survey-rs X` with no other change.
//!
//! Default subcommand (no args) is `serve` — preserves the existing launchd
//! plist invocation `auto-survey-rs serve`.

use anyhow::{bail, Context, Result};
use axum::{routing::get, Json, Router};
use chrono::{Local, Utc};
use clap::{Parser, Subcommand};
use serde_json::json;
use sqlx::{Row, SqlitePool};
use std::net::SocketAddr;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

mod analyzer;
mod config;
mod db;
mod filler;
mod line;
mod models;
mod notify;
mod ocr_client;
mod orchestrator;
mod playwright;
mod recon;
mod web;

use config::Settings;

#[derive(Parser, Debug)]
#[command(name = "auto-survey-rs", version, about = "SurveyCake attendance + quiz automation")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Start web UI server (default when no subcommand given).
    Serve {
        #[arg(long, default_value = "127.0.0.1")]
        host: String,
        #[arg(long)]
        port: Option<u16>,
    },
    /// Run attendance + quiz in one shot, tracking daily state.
    Run {
        #[arg(long = "attend-url")]
        attend_url: Option<String>,
        #[arg(long = "quiz-url")]
        quiz_url: Option<String>,
        #[arg(long = "dry-run")]
        dry_run: bool,
    },
    /// Fill attendance form for all active people.
    Attend {
        url: String,
        #[arg(long = "dry-run")]
        dry_run: bool,
    },
    /// Fill quiz form for all active people.
    Quiz {
        url: String,
        #[arg(long = "dry-run")]
        dry_run: bool,
    },
    /// Output today's DailyRun status and URLs (machine-readable key:value).
    TodayStatus,
    /// Check if today needs a reminder. Send Bark if no URLs provided yet.
    NotifyCheck,
    /// Single LINE read: screenshot + OCR → extract URLs → save to DB as scheduled.
    LineRead {
        #[arg(long)]
        group: Option<String>,
    },
    /// Poll LINE with retries until URLs appear or attempts exhausted.
    LinePoll {
        #[arg(long = "max-retries", default_value_t = 5)]
        max_retries: u32,
        #[arg(long, default_value_t = 120)]
        interval: u64,
        #[arg(long = "max-interval", default_value_t = 600)]
        max_interval: u64,
    },
    /// Show submission history.
    History {
        #[arg(long)]
        url: Option<String>,
        #[arg(long, default_value_t = 50)]
        limit: i64,
    },
    /// Manage people list.
    #[command(subcommand)]
    People(PeopleCmd),
    /// Initialise the database (runs migrations).
    Init,
}

#[derive(Subcommand, Debug)]
enum PeopleCmd {
    /// List all people.
    List,
    /// Add or update a person (upsert by email).
    Add {
        name: String,
        email: String,
        company: String,
    },
    /// Import people from a CSV file (columns: name, email, company).
    Import { csv_path: String },
    /// Deactivate a person by email (active=0).
    Deactivate { email: String },
    /// Reactivate a person by email (active=1).
    Activate { email: String },
}

#[tokio::main]
async fn main() -> Result<()> {
    // Route logs to stderr so CLI subcommands (today-status, history, etc.)
    // can emit parseable key:value lines on stdout without tracing noise.
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cli = Cli::parse();
    let cmd = cli.command.unwrap_or(Command::Serve {
        host: "127.0.0.1".to_string(),
        port: None,
    });

    let cfg = Settings::from_env();

    match cmd {
        Command::Serve { host, port } => serve(cfg, host, port).await,
        Command::Run {
            attend_url,
            quiz_url,
            dry_run,
        } => cmd_run(&cfg, attend_url, quiz_url, dry_run).await,
        Command::Attend { url, dry_run } => {
            let pool = open_pool(&cfg).await?;
            orchestrator::run_attendance(&pool, &cfg, &url, dry_run).await
        }
        Command::Quiz { url, dry_run } => {
            let pool = open_pool(&cfg).await?;
            orchestrator::run_quiz(&pool, &cfg, &url, dry_run).await
        }
        Command::TodayStatus => cmd_today_status(&cfg).await,
        Command::NotifyCheck => cmd_notify_check(&cfg).await,
        Command::LineRead { group } => cmd_line_read(&cfg, group).await,
        Command::LinePoll {
            max_retries,
            interval,
            max_interval,
        } => cmd_line_poll(&cfg, max_retries, interval, max_interval).await,
        Command::History { url, limit } => cmd_history(&cfg, url, limit).await,
        Command::People(sub) => cmd_people(&cfg, sub).await,
        Command::Init => {
            let _ = open_pool(&cfg).await?;
            println!("[auto-survey-rs] Database initialised at {}", cfg.sqlite_path);
            Ok(())
        }
    }
}

async fn open_pool(cfg: &Settings) -> Result<SqlitePool> {
    let pool = db::init_pool(&cfg.sqlite_path).await?;
    sqlx::migrate!("./migrations").run(&pool).await?;
    Ok(pool)
}

// ── serve ────────────────────────────────────────────────────────────────────

async fn serve(cfg: Settings, host: String, port_override: Option<u16>) -> Result<()> {
    tracing::info!("auto-survey-rs starting on port {}", cfg.web_port);
    let pool = open_pool(&cfg).await?;

    let state = web::AppState {
        pool,
        cfg: cfg.clone(),
    };

    let app = Router::new()
        .route("/status", get(status))
        .route("/health", get(status))
        .merge(web::routes())
        .with_state(state);

    let port = port_override.unwrap_or(cfg.web_port);
    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    tracing::info!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    Ok(())
}

async fn shutdown_signal() {
    use tokio::signal::unix::{signal, SignalKind};
    let mut term = signal(SignalKind::terminate()).expect("install SIGTERM handler");
    let mut intr = signal(SignalKind::interrupt()).expect("install SIGINT handler");
    tokio::select! {
        _ = term.recv() => tracing::info!("received SIGTERM, shutting down"),
        _ = intr.recv() => tracing::info!("received SIGINT, shutting down"),
    }
}

async fn status() -> Json<serde_json::Value> {
    Json(json!({
        "service": "auto-survey-rs",
        "version": env!("CARGO_PKG_VERSION"),
        "status": "ok",
    }))
}

// ── run (attend + quiz) ──────────────────────────────────────────────────────

async fn cmd_run(
    cfg: &Settings,
    attend_url: Option<String>,
    quiz_url: Option<String>,
    dry_run: bool,
) -> Result<()> {
    if attend_url.is_none() && quiz_url.is_none() {
        bail!("provide at least one of --attend-url or --quiz-url");
    }
    let pool = open_pool(cfg).await?;

    // Upsert DailyRun row → status=running.
    let today = today_str();
    let now = now_iso();
    let run_id: String = match sqlx::query("SELECT id FROM daily_runs WHERE run_date = ?")
        .bind(&today)
        .fetch_optional(&pool)
        .await?
    {
        Some(row) => {
            let id: String = row.get("id");
            sqlx::query(
                "UPDATE daily_runs SET attend_url=?, quiz_url=?, status='running', result_summary=NULL, updated_at=? WHERE id=?",
            )
            .bind(&attend_url)
            .bind(&quiz_url)
            .bind(&now)
            .bind(&id)
            .execute(&pool)
            .await?;
            id
        }
        None => {
            let id = Uuid::new_v4().to_string();
            sqlx::query(
                "INSERT INTO daily_runs (id, run_date, attend_url, quiz_url, status, created_at, updated_at) VALUES (?,?,?,?,'running',?,?)",
            )
            .bind(&id)
            .bind(&today)
            .bind(&attend_url)
            .bind(&quiz_url)
            .bind(&now)
            .bind(&now)
            .execute(&pool)
            .await?;
            id
        }
    };

    let mut results: Vec<String> = Vec::new();
    let mut any_failed = false;

    if let Some(url) = &attend_url {
        println!("[auto-survey] === Attendance: {url} ===");
        match orchestrator::run_attendance(&pool, cfg, url, dry_run).await {
            Ok(()) => results.push("attendance: OK".to_string()),
            Err(e) => {
                results.push(format!("attendance: FAILED ({e})"));
                any_failed = true;
            }
        }
    }
    if let Some(url) = &quiz_url {
        println!("[auto-survey] === Quiz: {url} ===");
        match orchestrator::run_quiz(&pool, cfg, url, dry_run).await {
            Ok(()) => results.push("quiz: OK".to_string()),
            Err(e) => {
                results.push(format!("quiz: FAILED ({e})"));
                any_failed = true;
            }
        }
    }

    let summary = results.join(" | ");
    let final_status = if any_failed { "failed" } else { "completed" };
    sqlx::query("UPDATE daily_runs SET status=?, result_summary=?, updated_at=? WHERE id=?")
        .bind(final_status)
        .bind(&summary)
        .bind(&now_iso())
        .bind(&run_id)
        .execute(&pool)
        .await?;

    let client = reqwest::Client::new();
    let marker = if any_failed { "!" } else { "OK" };
    let _ = notify::send_bark(&client, cfg, "Auto Survey", &format!("{marker} {summary}")).await;

    println!("[auto-survey] Done: {summary}");
    if any_failed {
        std::process::exit(1);
    }
    Ok(())
}

// ── today-status ─────────────────────────────────────────────────────────────

async fn cmd_today_status(cfg: &Settings) -> Result<()> {
    let pool = open_pool(cfg).await?;
    let today = today_str();
    let row = sqlx::query(
        "SELECT status, attend_url, quiz_url, result_summary FROM daily_runs WHERE run_date = ?",
    )
    .bind(&today)
    .fetch_optional(&pool)
    .await?;
    match row {
        None => println!("status:none"),
        Some(r) => {
            let s: String = r.get("status");
            let a: Option<String> = r.get("attend_url");
            let q: Option<String> = r.get("quiz_url");
            let sum: Option<String> = r.get("result_summary");
            println!("status:{s}");
            println!("attend_url:{}", a.unwrap_or_default());
            println!("quiz_url:{}", q.unwrap_or_default());
            println!("result_summary:{}", sum.unwrap_or_default());
        }
    }
    Ok(())
}

// ── notify-check ─────────────────────────────────────────────────────────────

async fn cmd_notify_check(cfg: &Settings) -> Result<()> {
    let pool = open_pool(cfg).await?;
    let today = today_str();
    let row = sqlx::query("SELECT status FROM daily_runs WHERE run_date = ?")
        .bind(&today)
        .fetch_optional(&pool)
        .await?;
    if let Some(r) = &row {
        let s: String = r.get("status");
        if matches!(s.as_str(), "running" | "completed" | "scheduled") {
            println!("[auto-survey] Today already {s}, skipping notification.");
            return Ok(());
        }
    }

    let client = reqwest::Client::new();
    let _ = notify::send_bark(
        &client,
        cfg,
        "Auto Survey Reminder",
        "今天有課程，請提供 SurveyCake URL",
    )
    .await;
    println!("[auto-survey] Reminder sent via Bark.");

    if row.is_none() {
        let id = Uuid::new_v4().to_string();
        let now = now_iso();
        sqlx::query(
            "INSERT INTO daily_runs (id, run_date, status, created_at, updated_at) VALUES (?,?, 'pending', ?, ?)",
        )
        .bind(&id)
        .bind(&today)
        .bind(&now)
        .bind(&now)
        .execute(&pool)
        .await?;
    }
    Ok(())
}

// ── line-read ────────────────────────────────────────────────────────────────

async fn cmd_line_read(cfg: &Settings, group: Option<String>) -> Result<()> {
    let community = group
        .clone()
        .unwrap_or_else(|| cfg.line_community_name.clone());
    println!("[auto-survey] Reading LINE community: {community}");

    let client = reqwest::Client::new();
    let urls = line::fetch_latest_survey_urls(cfg, &client, cfg.line_scroll_pages).await;
    if urls.is_empty() {
        println!("[auto-survey] Failed to read LINE (not running or no content)");
        std::process::exit(1);
    }

    // Classify by order: first = attend, second = quiz (mirrors Python fallback).
    let text = urls.join("\n");
    let (attend, quiz) = line::extract_survey_urls(&text);
    if attend.is_none() && quiz.is_none() {
        println!("[auto-survey] No SurveyCake URLs found in today's messages");
        std::process::exit(1);
    }
    if let Some(u) = &attend {
        println!("  簽到: {u}");
    }
    if let Some(u) = &quiz {
        println!("  測驗: {u}");
    }

    let pool = open_pool(cfg).await?;
    let today = today_str();
    let now = now_iso();
    let row = sqlx::query("SELECT id FROM daily_runs WHERE run_date = ?")
        .bind(&today)
        .fetch_optional(&pool)
        .await?;
    match row {
        Some(r) => {
            let id: String = r.get("id");
            sqlx::query(
                "UPDATE daily_runs SET attend_url=?, quiz_url=?, status='scheduled', updated_at=? WHERE id=?",
            )
            .bind(&attend)
            .bind(&quiz)
            .bind(&now)
            .bind(&id)
            .execute(&pool)
            .await?;
        }
        None => {
            let id = Uuid::new_v4().to_string();
            sqlx::query(
                "INSERT INTO daily_runs (id, run_date, attend_url, quiz_url, status, created_at, updated_at) VALUES (?,?,?,?,'scheduled',?,?)",
            )
            .bind(&id)
            .bind(&today)
            .bind(&attend)
            .bind(&quiz)
            .bind(&now)
            .bind(&now)
            .execute(&pool)
            .await?;
        }
    }
    println!("[auto-survey] URLs saved to DB (status: scheduled)");
    Ok(())
}

async fn cmd_line_poll(
    cfg: &Settings,
    max_retries: u32,
    interval: u64,
    max_interval: u64,
) -> Result<()> {
    for attempt in 1..=max_retries {
        println!("[auto-survey] LINE poll attempt {attempt}/{max_retries}");
        if cmd_line_read(cfg, None).await.is_ok() {
            return Ok(());
        }
        if attempt == max_retries {
            break;
        }
        let delay = (interval.saturating_mul(2u64.saturating_pow(attempt - 1))).min(max_interval);
        println!("[auto-survey] Retry in {delay}s");
        tokio::time::sleep(std::time::Duration::from_secs(delay)).await;
    }
    bail!("LINE poll exhausted all retries");
}

// ── history ──────────────────────────────────────────────────────────────────

async fn cmd_history(cfg: &Settings, url: Option<String>, limit: i64) -> Result<()> {
    let pool = open_pool(cfg).await?;
    let (sql, bind_url) = if let Some(u) = &url {
        (
            "SELECT sub.submitted_at, p.name, sv.url, sub.status, sub.score
             FROM submissions sub
             JOIN surveys sv ON sv.id = sub.survey_id
             JOIN people p  ON p.id = sub.person_id
             WHERE sv.url = ?
             ORDER BY sub.submitted_at DESC LIMIT ?",
            Some(u.clone()),
        )
    } else {
        (
            "SELECT sub.submitted_at, p.name, sv.url, sub.status, sub.score
             FROM submissions sub
             JOIN surveys sv ON sv.id = sub.survey_id
             JOIN people p  ON p.id = sub.person_id
             ORDER BY sub.submitted_at DESC LIMIT ?",
            None,
        )
    };
    let mut q = sqlx::query(sql);
    if let Some(u) = &bind_url {
        q = q.bind(u);
    }
    q = q.bind(limit);
    let rows = q.fetch_all(&pool).await?;
    if rows.is_empty() {
        println!("No submissions found.");
        return Ok(());
    }
    println!("{:<20} {:<15} {:<30} {:<10} Score", "Date", "Name", "Survey", "Status");
    println!("{}", "-".repeat(85));
    for r in rows {
        let dt: String = r.get("submitted_at");
        let name: String = r.get("name");
        let u: String = r.get("url");
        let status: String = r.get("status");
        let score: Option<i64> = r.get("score");
        let short_dt = dt.get(..16).unwrap_or(&dt);
        let short_url = if u.len() > 30 { &u[..30] } else { &u };
        let score_str = score.map(|s| s.to_string()).unwrap_or_default();
        println!(
            "{:<20} {:<15} {:<30} {:<10} {}",
            short_dt, name, short_url, status, score_str
        );
    }
    Ok(())
}

// ── people ───────────────────────────────────────────────────────────────────

async fn cmd_people(cfg: &Settings, sub: PeopleCmd) -> Result<()> {
    let pool = open_pool(cfg).await?;
    match sub {
        PeopleCmd::List => {
            let rows =
                sqlx::query("SELECT name, email, company, active FROM people ORDER BY name")
                    .fetch_all(&pool)
                    .await?;
            if rows.is_empty() {
                println!("No people found.");
                return Ok(());
            }
            println!(
                "{:<20} {:<35} {:<15} Active",
                "Name", "Email", "Company"
            );
            println!("{}", "-".repeat(75));
            for r in rows {
                let n: String = r.get("name");
                let e: String = r.get("email");
                let c: String = r.get("company");
                let a: i64 = r.get("active");
                println!(
                    "{:<20} {:<35} {:<15} {}",
                    n,
                    e,
                    c,
                    if a != 0 { "Y" } else { "N" }
                );
            }
        }
        PeopleCmd::Add { name, email, company } => {
            upsert_person(&pool, &name, &email, &company, true).await?;
            println!("Added/updated: {name} <{email}>");
        }
        PeopleCmd::Import { csv_path } => {
            let data = std::fs::read_to_string(&csv_path)
                .with_context(|| format!("read csv {csv_path}"))?;
            let mut rdr = csv::ReaderBuilder::new()
                .has_headers(true)
                .from_reader(data.as_bytes());
            let mut count = 0;
            for rec in rdr.deserialize::<CsvPerson>() {
                let p = match rec {
                    Ok(p) => p,
                    Err(e) => {
                        println!("Skipping row (parse err): {e}");
                        continue;
                    }
                };
                if p.name.trim().is_empty()
                    || p.email.trim().is_empty()
                    || p.company.trim().is_empty()
                {
                    println!("Skipping incomplete row: {:?}", p);
                    continue;
                }
                upsert_person(&pool, p.name.trim(), p.email.trim(), p.company.trim(), true)
                    .await?;
                count += 1;
            }
            println!("Imported {count} people.");
        }
        PeopleCmd::Deactivate { email } => {
            let n = sqlx::query("UPDATE people SET active = 0 WHERE email = ?")
                .bind(&email)
                .execute(&pool)
                .await?
                .rows_affected();
            if n == 0 {
                println!("Person not found: {email}");
            } else {
                println!("Deactivated: {email}");
            }
        }
        PeopleCmd::Activate { email } => {
            let n = sqlx::query("UPDATE people SET active = 1 WHERE email = ?")
                .bind(&email)
                .execute(&pool)
                .await?
                .rows_affected();
            if n == 0 {
                println!("Person not found: {email}");
            } else {
                println!("Activated: {email}");
            }
        }
    }
    Ok(())
}

async fn upsert_person(
    pool: &SqlitePool,
    name: &str,
    email: &str,
    company: &str,
    active: bool,
) -> Result<()> {
    let existing = sqlx::query("SELECT id FROM people WHERE email = ?")
        .bind(email)
        .fetch_optional(pool)
        .await?;
    match existing {
        Some(r) => {
            let id: String = r.get("id");
            sqlx::query("UPDATE people SET name=?, company=?, active=? WHERE id=?")
                .bind(name)
                .bind(company)
                .bind(if active { 1i64 } else { 0 })
                .bind(&id)
                .execute(pool)
                .await?;
        }
        None => {
            let id = Uuid::new_v4().to_string();
            let now = now_iso();
            sqlx::query("INSERT INTO people (id, name, email, company, active, created_at) VALUES (?,?,?,?,?,?)")
                .bind(&id)
                .bind(name)
                .bind(email)
                .bind(company)
                .bind(if active { 1i64 } else { 0 })
                .bind(&now)
                .execute(pool)
                .await?;
        }
    }
    Ok(())
}

#[derive(Debug, serde::Deserialize)]
struct CsvPerson {
    name: String,
    email: String,
    company: String,
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn today_str() -> String {
    Local::now().format("%Y-%m-%d").to_string()
}
fn now_iso() -> String {
    Utc::now().to_rfc3339()
}
