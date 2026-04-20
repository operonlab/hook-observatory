//! Pipeline orchestrator — coordinates recon, analyze, and fill phases.
//! Mirrors Python `orchestrator.py` line-for-line.

use crate::analyzer::{analyze_quiz, is_transient_error, reanalyze_wrong};
use crate::config::Settings;
use crate::filler::fill_form;
use crate::models::{Person, Submission, Survey};
use crate::playwright::{cleanup_session, create_session};
use crate::recon::{classify_subjects, recon_survey, save_survey};
use anyhow::{Context, Result};
use rand::seq::SliceRandom;
use rand::Rng;
use sqlx::SqlitePool;
use std::collections::HashMap;
use tokio::time::{sleep, Duration};

/// Phase 1 (recon) + Phase 2 (analyze) max retry attempts.
/// Phase 3 (fill) is NEVER retried here — individual fill errors are
/// handled inside `filler::fill_form` to prevent double-submission.
const RECON_ANALYZE_MAX_ATTEMPTS: u32 = 2;

// ── Public entry points ───────────────────────────────────────────────────────

pub async fn run_attendance(pool: &SqlitePool, cfg: &Settings, url: &str, dry_run: bool) -> Result<()> {
    run_pipeline(pool, cfg, url, "attendance", dry_run).await
}

pub async fn run_quiz(pool: &SqlitePool, cfg: &Settings, url: &str, dry_run: bool) -> Result<()> {
    run_pipeline(pool, cfg, url, "quiz", dry_run).await
}

// ── recon_and_analyze ─────────────────────────────────────────────────────────

/// Phase 1 (recon) + Phase 2 (analyze) wrapped in one retry unit.
///
/// Both phases are read-only against SurveyCake and idempotent against the DB
/// (upsert Survey by URL). We retry together so that a fresh browser session +
/// fresh LLM client are used on each attempt.
///
/// Mirrors Python `_recon_and_analyze(db, url, survey_type)`.
pub async fn recon_and_analyze(
    pool: &SqlitePool,
    cfg: &Settings,
    url: &str,
    survey_type: &str,
) -> Result<(Survey, HashMap<String, String>)> {
    let mut last_err: Option<anyhow::Error> = None;

    for attempt in 1..=RECON_ANALYZE_MAX_ATTEMPTS {
        tracing::info!(
            "Phase 1: Recon — extracting form structure... (attempt {}/{})",
            attempt,
            RECON_ANALYZE_MAX_ATTEMPTS
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

// ── run_pipeline ──────────────────────────────────────────────────────────────

/// Full pipeline: recon → analyze → fill (with pathfinder logic).
/// Mirrors Python `_run_pipeline(db, url, survey_type, dry_run)`.
async fn run_pipeline(
    pool: &SqlitePool,
    cfg: &Settings,
    url: &str,
    survey_type: &str,
    dry_run: bool,
) -> Result<()> {
    let people = fetch_active_people(pool).await?;
    if people.is_empty() {
        tracing::info!("No active people found. Import with: auto-survey-rs people import <csv>");
        return Ok(());
    }
    tracing::info!("Found {} active people", people.len());

    // Phase 1 + Phase 2 (retriable — read-only, idempotent)
    let (survey, mut answers) = recon_and_analyze(pool, cfg, url, survey_type).await?;

    if dry_run {
        tracing::info!("Dry run — skipping form filling");
        return Ok(());
    }

    // Phase 3: Fill
    tracing::info!("Phase 3: Fill — submitting forms...");

    // Shuffle people — first becomes pathfinder (HANDOFF quirk 5)
    let mut people = people;
    people.shuffle(&mut rand::thread_rng());

    let remaining = if survey_type == "quiz" && !answers.is_empty() {
        let scout = &people[0];
        tracing::info!("Pathfinder: {} goes first...", scout.name);
        fill_one_person(pool, cfg, &survey, scout, Some(&answers)).await;

        // Mark as pathfinder (HANDOFF quirk 4)
        let sub = fetch_submission_for(pool, &survey.id.to_string(), &scout.id.to_string()).await?;
        if let Some(ref s) = sub {
            mark_pathfinder(pool, &s.id.to_string()).await.ok();

            if s.status == "success" {
                if let Some(score) = s.score {
                    tracing::info!("  Pathfinder score: {}", score);
                    if score < 100 {
                        tracing::info!("  Score < 100 — re-analyzing wrong answers...");
                        let all_subjects: Vec<String> = answers.keys().cloned().collect();
                        let new_answers = reanalyze_wrong(pool, survey.id, &all_subjects, cfg).await?;
                        let updated = new_answers.len();
                        answers.extend(new_answers);
                        tracing::info!("  Updated {} answers", updated);
                    }
                } else {
                    tracing::info!("  Could not extract score — proceeding with current answers");
                }
            }
        }

        &people[1..]
    } else {
        &people[..]
    };

    // Fill remaining people (HANDOFF quirk 6: stagger delay; quirk 7: skip already-success)
    for (i, person) in remaining.iter().enumerate() {
        let existing = fetch_submission_for(pool, &survey.id.to_string(), &person.id.to_string()).await?;
        if matches!(existing.as_ref().map(|s| s.status.as_str()), Some("success")) {
            tracing::info!(
                "  [{}/{}] {} — already submitted, skipping",
                i + 1,
                remaining.len(),
                person.name
            );
            continue;
        }

        // Stagger delay between submissions (not before the first one)
        if i > 0 {
            let delay = rand::thread_rng().gen_range(cfg.min_delay..=cfg.max_delay);
            tracing::info!("  Waiting {}s before next submission...", delay);
            sleep(Duration::from_secs(delay)).await;
        }

        tracing::info!("  [{}/{}] {}...", i + 1, remaining.len(), person.name);
        let ans_opt = if survey_type == "quiz" { Some(&answers) } else { None };
        fill_one_person(pool, cfg, &survey, person, ans_opt).await;

        if let Ok(Some(sub)) =
            fetch_submission_for(pool, &survey.id.to_string(), &person.id.to_string()).await
        {
            let score_str = sub
                .score
                .map(|s| format!(" (score: {})", s))
                .unwrap_or_default();
            let err_str = sub
                .error_message
                .as_deref()
                .map(|e| format!(" — {e}"))
                .unwrap_or_default();
            tracing::info!("    Result: {}{}{}", sub.status, score_str, err_str);
        }
    }

    print_summary(pool, &survey).await;
    Ok(())
}

// ── helpers ───────────────────────────────────────────────────────────────────

/// Fill form for one person — creates its own browser session.
/// Mirrors Python `_fill_one_person`.
async fn fill_one_person(
    pool: &SqlitePool,
    cfg: &Settings,
    survey: &Survey,
    person: &Person,
    answers: Option<&HashMap<String, String>>,
) {
    let pw = create_session(cfg.clone()).await;
    let result = fill_form(pw.as_ref(), pool, survey, person, answers).await;
    pw.close().await.ok();
    cleanup_session(pw.as_ref());
    if let Err(e) = result {
        tracing::error!("fill_form error for {}: {}", person.name, e);
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
    tracing::info!("Summary: {}/{} success, {} failed", success, total, failed);

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
    // Best-effort: extract type from Debug output first line
    let dbg = format!("{e:?}");
    dbg.lines().next().unwrap_or("Error").to_string()
}
