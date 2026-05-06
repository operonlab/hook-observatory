//! Pipeline orchestrator — coordinates recon, analyze, and fill phases.
//!
//! Architecture:
//! - `run_attendance` / `run_quiz`: single-survey path with parallel fan-out.
//!   Quiz path uses pathfinder gate (score must hit 100 before others run).
//! - `run_combined`: per-person attend+quiz pipeline. Pathfinder gates the
//!   quiz answers, then remaining people fan out (each runs attend → quiz
//!   sequentially within their own task).

use crate::analyzer::{analyze_quiz, is_transient_error, reanalyze_wrong};
use crate::config::Settings;
use crate::filler::fill_form;
use crate::models::{Person, Submission, Survey};
use crate::playwright::{cleanup_session, create_session};
use crate::recon::{classify_subjects, recon_survey, save_survey};
use anyhow::{Context, Result};
use rand::seq::SliceRandom;
use sqlx::SqlitePool;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::{sleep, Duration, Instant};

const RECON_ANALYZE_MAX_ATTEMPTS: u32 = 2;
/// Pathfinder retry cap when score < 100. Each retry re-analyzes wrong
/// answers and resubmits (after deleting the previous submission row).
const PATHFINDER_MAX_ATTEMPTS: u32 = 3;

// ── Public entry points ───────────────────────────────────────────────────────

pub async fn run_attendance(pool: &SqlitePool, cfg: &Settings, url: &str, dry_run: bool) -> Result<()> {
    let people = fetch_active_people(pool).await?;
    if people.is_empty() {
        tracing::info!("No active people found. Import with: auto-survey-rs people import <csv>");
        return Ok(());
    }
    tracing::info!("Found {} active people", people.len());

    let (survey, _) = recon_and_analyze(pool, cfg, url, "attendance").await?;
    if dry_run {
        tracing::info!("Dry run — skipping form filling");
        return Ok(());
    }

    let started = Instant::now();
    parallel_fill(pool, cfg, &survey, &people, None, cfg.concurrency).await;
    log_budget("attendance", started, cfg.time_budget_secs);
    print_summary(pool, &survey).await;
    Ok(())
}

pub async fn run_quiz(pool: &SqlitePool, cfg: &Settings, url: &str, dry_run: bool) -> Result<()> {
    let people = fetch_active_people(pool).await?;
    if people.is_empty() {
        tracing::info!("No active people found. Import with: auto-survey-rs people import <csv>");
        return Ok(());
    }
    tracing::info!("Found {} active people", people.len());

    let (survey, mut answers) = recon_and_analyze(pool, cfg, url, "quiz").await?;
    if dry_run {
        tracing::info!("Dry run — skipping form filling");
        return Ok(());
    }

    let mut shuffled = people;
    shuffled.shuffle(&mut rand::thread_rng());
    let scout = shuffled[0].clone();

    let started = Instant::now();
    answers = pathfinder_quiz_loop(pool, cfg, &survey, &scout, answers).await?;

    let remaining: Vec<Person> = shuffled.iter().skip(1).cloned().collect();
    parallel_fill(pool, cfg, &survey, &remaining, Some(&answers), cfg.concurrency).await;
    log_budget("quiz", started, cfg.time_budget_secs);
    print_summary(pool, &survey).await;
    Ok(())
}

/// Combined attend + quiz with per-person pipeline.
///
/// Stages:
/// 1. Recon attend + recon quiz (+ analyze) in parallel — `tokio::try_join!`.
/// 2. Pathfinder runs quiz only and must reach score 100 (re-analyze + retry
///    up to `PATHFINDER_MAX_ATTEMPTS`). Gate blocks fan-out until 100 (or
///    retries exhausted).
/// 3. Fan-out (semaphore-bounded `JoinSet`):
///    - Pathfinder task: attend only (quiz already done).
///    - Other tasks: attend → quiz sequentially within the task.
pub async fn run_combined(
    pool: &SqlitePool,
    cfg: &Settings,
    attend_url: &str,
    quiz_url: &str,
    dry_run: bool,
) -> Result<()> {
    let people = fetch_active_people(pool).await?;
    if people.is_empty() {
        tracing::info!("No active people found.");
        return Ok(());
    }
    tracing::info!("Found {} active people", people.len());

    // Stage 1: recon both surveys + analyze quiz, in parallel.
    tracing::info!("Stage 1: Recon attend + quiz in parallel");
    let attend_fut = recon_and_analyze(pool, cfg, attend_url, "attendance");
    let quiz_fut = recon_and_analyze(pool, cfg, quiz_url, "quiz");
    let ((attend_survey, _), (quiz_survey, mut answers)) =
        tokio::try_join!(attend_fut, quiz_fut)?;

    if dry_run {
        tracing::info!("Dry run — skipping form filling");
        return Ok(());
    }

    let started = Instant::now();

    // Stage 2: pathfinder gate on quiz.
    let mut shuffled = people;
    shuffled.shuffle(&mut rand::thread_rng());
    let scout = shuffled[0].clone();
    tracing::info!("Stage 2: Pathfinder gate — {} runs quiz first", scout.name);
    answers = pathfinder_quiz_loop(pool, cfg, &quiz_survey, &scout, answers).await?;

    // Stage 3: fan-out per-person pipeline.
    let remaining: Vec<Person> = shuffled.iter().skip(1).cloned().collect();
    tracing::info!(
        "Stage 3: Fan-out (concurrency={}, remaining={}, +1 pathfinder attend)",
        cfg.concurrency,
        remaining.len()
    );
    fan_out_pipeline(pool, cfg, &attend_survey, &quiz_survey, &scout, &remaining, &answers).await;

    log_budget("combined", started, cfg.time_budget_secs);
    print_summary(pool, &attend_survey).await;
    print_summary(pool, &quiz_survey).await;
    Ok(())
}

// ── recon_and_analyze ─────────────────────────────────────────────────────────

pub async fn recon_and_analyze(
    pool: &SqlitePool,
    cfg: &Settings,
    url: &str,
    survey_type: &str,
) -> Result<(Survey, HashMap<String, String>)> {
    let mut last_err: Option<anyhow::Error> = None;

    for attempt in 1..=RECON_ANALYZE_MAX_ATTEMPTS {
        tracing::info!(
            "Phase 1: Recon — extracting form structure... (attempt {}/{}, type={})",
            attempt,
            RECON_ANALYZE_MAX_ATTEMPTS,
            survey_type
        );

        match do_recon_analyze(pool, cfg, url, survey_type).await {
            Ok(result) => return Ok(result),
            Err(e) => {
                let transient = is_transient_error(&e);
                if attempt == RECON_ANALYZE_MAX_ATTEMPTS || !transient {
                    return Err(e);
                }
                let backoff = 3 * attempt;
                tracing::warn!(
                    "  Recon/Analyze transient error ({}): {} — retry in {}s",
                    type_name_of_error(&e),
                    &format!("{e}")[..format!("{e}").len().min(160)],
                    backoff
                );
                last_err = Some(e);
                sleep(Duration::from_secs(backoff as u64)).await;
            }
        }
    }

    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("Recon/Analyze exhausted retries")))
}

async fn do_recon_analyze(
    pool: &SqlitePool,
    cfg: &Settings,
    url: &str,
    survey_type: &str,
) -> Result<(Survey, HashMap<String, String>)> {
    let pw = create_session(cfg.clone()).await;

    let (survey, answers) = {
        let structure = recon_survey(pw.as_ref(), url).await?;
        let classified = classify_subjects(&structure.subjects);
        let survey = save_survey(pool, url, survey_type, &structure, &classified).await?;

        tracing::info!("Survey: {} ({})", survey.title.as_deref().unwrap_or("?"), survey.survey_type);
        if !classified.questions.is_empty() {
            tracing::info!("  Found {} quiz questions", classified.questions.len());
        }
        if let Some(ref c) = classified.company {
            tracing::info!("  Company options: {:?}", c.options);
        }

        pw.close().await.ok();
        cleanup_session(pw.as_ref());

        let answers: HashMap<String, String> =
            if survey_type == "quiz" && !classified.questions.is_empty() {
                tracing::info!("Phase 2: Analyze — getting answers from LLM...");
                let ans = analyze_quiz(pool, survey.id, cfg).await?;
                tracing::info!("  Got {} answers", ans.len());
                for (sid, a) in &ans {
                    tracing::info!("    {}: {}", sid, a);
                }
                ans
            } else {
                HashMap::new()
            };

        (survey, answers)
    };

    Ok((survey, answers))
}

// ── pathfinder_quiz_loop ──────────────────────────────────────────────────────

/// Run quiz for the pathfinder. If score < 100, re-analyze wrong answers,
/// delete the old submission, and retry up to `PATHFINDER_MAX_ATTEMPTS`.
/// Returns the (possibly updated) answers map for downstream fan-out.
async fn pathfinder_quiz_loop(
    pool: &SqlitePool,
    cfg: &Settings,
    survey: &Survey,
    scout: &Person,
    mut answers: HashMap<String, String>,
) -> Result<HashMap<String, String>> {
    for attempt in 1..=PATHFINDER_MAX_ATTEMPTS {
        tracing::info!(
            "  Pathfinder {} attempt {}/{}",
            scout.name, attempt, PATHFINDER_MAX_ATTEMPTS
        );

        fill_one_person_inner(pool, cfg, survey, scout, Some(&answers)).await;

        let Some(sub) =
            fetch_submission_for(pool, &survey.id.to_string(), &scout.id.to_string()).await?
        else {
            tracing::warn!("  Pathfinder submission row missing — proceeding with current answers");
            return Ok(answers);
        };

        let _ = mark_pathfinder(pool, &sub.id.to_string()).await;

        if sub.status != "success" {
            tracing::warn!(
                "  Pathfinder failed: status={} err={:?} — proceeding (gate forced open)",
                sub.status, sub.error_message
            );
            return Ok(answers);
        }

        match sub.score {
            Some(100) => {
                tracing::info!("  Pathfinder score 100 — gate open");
                return Ok(answers);
            }
            Some(s) if attempt < PATHFINDER_MAX_ATTEMPTS => {
                tracing::info!("  Pathfinder score {} — re-analyzing wrong answers and retrying", s);
                let all_subjects: Vec<String> = answers.keys().cloned().collect();
                let new_answers = reanalyze_wrong(pool, survey.id, &all_subjects, cfg).await?;
                let updated = new_answers.len();
                answers.extend(new_answers);
                tracing::info!("  Updated {} answers", updated);
                // Allow re-fill on next attempt — fill_form short-circuits on success rows.
                delete_submission(pool, &sub.id.to_string()).await?;
            }
            Some(s) => {
                tracing::warn!(
                    "  Pathfinder score {} after {} attempts — gate forced open",
                    s, PATHFINDER_MAX_ATTEMPTS
                );
                return Ok(answers);
            }
            None => {
                tracing::warn!("  Pathfinder score not extracted — gate forced open");
                return Ok(answers);
            }
        }
    }
    Ok(answers)
}

// ── parallel_fill ─────────────────────────────────────────────────────────────

/// Fan out submissions for one survey across `people` concurrently.
async fn parallel_fill(
    pool: &SqlitePool,
    cfg: &Settings,
    survey: &Survey,
    people: &[Person],
    answers: Option<&HashMap<String, String>>,
    concurrency: usize,
) {
    if people.is_empty() {
        return;
    }
    let n = concurrency.max(1).min(people.len());
    let sem = Arc::new(Semaphore::new(n));
    let mut joinset: JoinSet<String> = JoinSet::new();
    let answers = answers.cloned();

    for person in people.iter().cloned() {
        let permit = sem
            .clone()
            .acquire_owned()
            .await
            .expect("semaphore closed");
        let pool = pool.clone();
        let cfg = cfg.clone();
        let survey = survey.clone();
        let answers = answers.clone();
        joinset.spawn(async move {
            let _permit = permit;
            fill_one_person_inner(&pool, &cfg, &survey, &person, answers.as_ref()).await;
            person.name
        });
    }

    while let Some(res) = joinset.join_next().await {
        if let Err(e) = res {
            tracing::error!("  task join error: {}", e);
        }
    }
}

// ── fan_out_pipeline (combined attend + quiz) ─────────────────────────────────

/// Pathfinder spawns an attend-only task. Each non-pathfinder person spawns a
/// task that runs attend → quiz sequentially.
async fn fan_out_pipeline(
    pool: &SqlitePool,
    cfg: &Settings,
    attend_survey: &Survey,
    quiz_survey: &Survey,
    scout: &Person,
    remaining: &[Person],
    answers: &HashMap<String, String>,
) {
    let total = remaining.len() + 1;
    let n = cfg.concurrency.max(1).min(total);
    let sem = Arc::new(Semaphore::new(n));
    let mut joinset: JoinSet<String> = JoinSet::new();

    {
        let permit = sem
            .clone()
            .acquire_owned()
            .await
            .expect("semaphore closed");
        let pool = pool.clone();
        let cfg = cfg.clone();
        let attend_survey = attend_survey.clone();
        let scout = scout.clone();
        joinset.spawn(async move {
            let _permit = permit;
            fill_one_person_inner(&pool, &cfg, &attend_survey, &scout, None).await;
            format!("{} (pathfinder/attend)", scout.name)
        });
    }

    for person in remaining.iter().cloned() {
        let permit = sem
            .clone()
            .acquire_owned()
            .await
            .expect("semaphore closed");
        let pool = pool.clone();
        let cfg = cfg.clone();
        let attend_survey = attend_survey.clone();
        let quiz_survey = quiz_survey.clone();
        let answers = answers.clone();
        joinset.spawn(async move {
            let _permit = permit;
            fill_one_person_inner(&pool, &cfg, &attend_survey, &person, None).await;
            fill_one_person_inner(&pool, &cfg, &quiz_survey, &person, Some(&answers)).await;
            person.name
        });
    }

    while let Some(res) = joinset.join_next().await {
        if let Err(e) = res {
            tracing::error!("  task join error: {}", e);
        }
    }
}

// ── helpers ───────────────────────────────────────────────────────────────────

async fn fill_one_person_inner(
    pool: &SqlitePool,
    cfg: &Settings,
    survey: &Survey,
    person: &Person,
    answers: Option<&HashMap<String, String>>,
) {
    tracing::info!("  [{}] {} — submitting...", survey.survey_type, person.name);
    let pw = create_session(cfg.clone()).await;
    let result = fill_form(pw.as_ref(), pool, survey, person, answers).await;
    pw.close().await.ok();
    cleanup_session(pw.as_ref());

    if let Err(e) = result {
        tracing::error!("    fill_form error for {}: {}", person.name, e);
        return;
    }

    if let Ok(Some(sub)) =
        fetch_submission_for(pool, &survey.id.to_string(), &person.id.to_string()).await
    {
        let score_str = sub.score.map(|s| format!(" (score: {})", s)).unwrap_or_default();
        let err_str = sub
            .error_message
            .as_deref()
            .map(|e| format!(" — {e}"))
            .unwrap_or_default();
        tracing::info!(
            "    [{}] {} → {}{}{}",
            survey.survey_type, person.name, sub.status, score_str, err_str
        );
    }
}

fn log_budget(label: &str, started: Instant, budget_secs: u64) {
    let elapsed = started.elapsed().as_secs_f64();
    let over = elapsed > budget_secs as f64;
    if over {
        tracing::warn!(
            "[{}] elapsed {:.1}s — over budget {}s",
            label, elapsed, budget_secs
        );
    } else {
        tracing::info!(
            "[{}] elapsed {:.1}s (budget {}s)",
            label, elapsed, budget_secs
        );
    }
}

async fn fetch_active_people(pool: &SqlitePool) -> Result<Vec<Person>> {
    struct Row {
        id: String,
        name: String,
        email: String,
        company: String,
        active: i64,
        created_at: String,
    }
    let rows = sqlx::query_as!(
        Row,
        r#"SELECT
            id AS "id!",
            name AS "name!",
            email AS "email!",
            company AS "company!",
            active AS "active!: i64",
            created_at AS "created_at!"
        FROM people WHERE active = 1"#
    )
    .fetch_all(pool)
    .await?;

    rows.into_iter()
        .map(|r| -> Result<Person> {
            Ok(Person {
                id: uuid::Uuid::parse_str(&r.id)
                    .with_context(|| format!("invalid UUID in people.id: {}", r.id))?,
                name: r.name,
                email: r.email,
                company: r.company,
                active: r.active != 0,
                created_at: r
                    .created_at
                    .parse()
                    .with_context(|| format!("invalid timestamp: {}", r.created_at))?,
            })
        })
        .collect()
}

async fn fetch_submission_for(
    pool: &SqlitePool,
    survey_id: &str,
    person_id: &str,
) -> Result<Option<Submission>> {
    struct Row {
        id: String,
        survey_id: String,
        person_id: String,
        status: String,
        score: Option<i64>,
        is_pathfinder: i64,
        answers_snapshot: Option<String>,
        error_message: Option<String>,
        submitted_at: String,
    }
    let row = sqlx::query_as!(
        Row,
        r#"SELECT
            id AS "id!",
            survey_id AS "survey_id!",
            person_id AS "person_id!",
            status AS "status!",
            score,
            is_pathfinder AS "is_pathfinder!: i64",
            answers_snapshot,
            error_message,
            submitted_at AS "submitted_at!"
        FROM submissions WHERE survey_id = ? AND person_id = ?"#,
        survey_id,
        person_id
    )
    .fetch_optional(pool)
    .await?;

    row.map(|r| -> Result<Submission> {
        Ok(Submission {
            id: uuid::Uuid::parse_str(&r.id)
                .with_context(|| format!("invalid UUID in submissions.id: {}", r.id))?,
            survey_id: uuid::Uuid::parse_str(&r.survey_id)
                .with_context(|| format!("invalid UUID in submissions.survey_id: {}", r.survey_id))?,
            person_id: uuid::Uuid::parse_str(&r.person_id)
                .with_context(|| format!("invalid UUID in submissions.person_id: {}", r.person_id))?,
            status: r.status,
            score: r.score.map(|s| s as i32),
            is_pathfinder: r.is_pathfinder != 0,
            answers_snapshot: r
                .answers_snapshot
                .as_deref()
                .and_then(|s| serde_json::from_str(s).ok()),
            error_message: r.error_message,
            submitted_at: r
                .submitted_at
                .parse()
                .with_context(|| format!("invalid timestamp: {}", r.submitted_at))?,
        })
    })
    .transpose()
}

async fn mark_pathfinder(pool: &SqlitePool, submission_id: &str) -> Result<()> {
    sqlx::query!(
        "UPDATE submissions SET is_pathfinder = 1 WHERE id = ?",
        submission_id
    )
    .execute(pool)
    .await?;
    Ok(())
}

async fn delete_submission(pool: &SqlitePool, submission_id: &str) -> Result<()> {
    sqlx::query!("DELETE FROM submissions WHERE id = ?", submission_id)
        .execute(pool)
        .await?;
    Ok(())
}

async fn print_summary(pool: &SqlitePool, survey: &Survey) {
    let survey_id = survey.id.to_string();
    let Ok(subs) = sqlx::query!(
        "SELECT status, score FROM submissions WHERE survey_id = ?",
        survey_id
    )
    .fetch_all(pool)
    .await else {
        return;
    };

    let total = subs.len();
    let success = subs.iter().filter(|s| s.status == "success").count();
    let failed = subs.iter().filter(|s| s.status == "failed").count();

    tracing::info!("{}", "=".repeat(50));
    tracing::info!(
        "[{}] Summary: {}/{} success, {} failed",
        survey.survey_type, success, total, failed
    );

    if survey.survey_type == "quiz" {
        let scores: Vec<i32> = subs
            .iter()
            .filter_map(|s| s.score.map(|sc| sc as i32))
            .collect();
        if !scores.is_empty() {
            let avg = scores.iter().sum::<i32>() as f64 / scores.len() as f64;
            let min = scores.iter().min().unwrap();
            let max = scores.iter().max().unwrap();
            let passed = scores.iter().filter(|&&s| s >= 60).count();
            tracing::info!("  Avg score: {:.1}", avg);
            tracing::info!("  Min: {}, Max: {}", min, max);
            tracing::info!("  Pass rate (>=60): {}/{}", passed, scores.len());
        }
    }
}

fn type_name_of_error(e: &anyhow::Error) -> String {
    let dbg = format!("{e:?}");
    dbg.lines().next().unwrap_or("Error").to_string()
}
