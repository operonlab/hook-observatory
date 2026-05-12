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
use crate::models::{Person, Question, Submission, Survey};
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
/// LLM 重新分析的最大嘗試次數（attempt 1..=3）。
/// 三次仍 < 100 會進入投票 fallback（attempt 4 多數派 / attempt 5 少數派）。
const PATHFINDER_LLM_MAX_ATTEMPTS: u32 = 3;
/// 多數派 / 少數派改投觸發門檻。LLM 答案在 options 索引上集中度 >= 此比例才動作。
const VOTE_SWAP_THRESHOLD: f64 = 0.8;

// ── Public entry points ───────────────────────────────────────────────────────

pub async fn run_attendance(pool: &SqlitePool, cfg: &Settings, url: &str, dry_run: bool) -> Result<()> {
    let people = fetch_active_people(pool).await?;
    if people.is_empty() {
        tracing::info!("No active people found. Import with: auto-survey people import <csv>");
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
        tracing::info!("No active people found. Import with: auto-survey people import <csv>");
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
///    up to `PATHFINDER_LLM_MAX_ATTEMPTS`, with vote-swap fallback). Gate blocks fan-out until 100 (or
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

/// Pathfinder 兩階段流程：
/// Phase A — LLM reanalyze (attempts 1..=PATHFINDER_LLM_MAX_ATTEMPTS)
/// Phase B — vote-swap fallback（多數派改投 → 少數派改投，取最高分）
async fn pathfinder_quiz_loop(
    pool: &SqlitePool,
    cfg: &Settings,
    survey: &Survey,
    scout: &Person,
    mut answers: HashMap<String, String>,
) -> Result<HashMap<String, String>> {
    for attempt in 1..=PATHFINDER_LLM_MAX_ATTEMPTS {
        tracing::info!(
            "  Pathfinder {} attempt {}/{} (LLM)",
            scout.name, attempt, PATHFINDER_LLM_MAX_ATTEMPTS
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
            Some(s) if attempt < PATHFINDER_LLM_MAX_ATTEMPTS => {
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
                tracing::info!(
                    "  Pathfinder LLM phase done, score {} after {} attempts — entering vote-swap fallback",
                    s, attempt
                );
                return vote_swap_fallback(
                    pool,
                    cfg,
                    survey,
                    scout,
                    answers,
                    s,
                    sub.id.to_string(),
                )
                .await;
            }
            None => {
                tracing::warn!("  Pathfinder score not extracted — gate forced open");
                return Ok(answers);
            }
        }
    }
    Ok(answers)
}

// ── vote_swap_fallback (Phase B) ──────────────────────────────────────────────

/// Phase B：當 LLM 三次重新分析仍 < 100 時，嘗試「答案索引投票」改投策略。
/// 流程：
///   attempt 4 = majority swap：把索引異於眾數的題目改成眾數對應選項
///   attempt 5 = minority swap：從 LLM 結果起算，挑 1 題眾數題改成次大眾數選項
///   結束：在 (attempt3, 4, 5) 中取最高分，若 surveycake 端最後一次提交不是最高分再做一次補救提交
async fn vote_swap_fallback(
    pool: &SqlitePool,
    cfg: &Settings,
    survey: &Survey,
    scout: &Person,
    base_answers: HashMap<String, String>,
    base_score: i32,
    base_submission_id: String,
) -> Result<HashMap<String, String>> {
    let questions = fetch_questions(pool, &survey.id.to_string()).await?;
    if questions.is_empty() {
        tracing::warn!("  vote-swap fallback: no questions found — gate forced open");
        return Ok(base_answers);
    }

    let mut best_answers = base_answers.clone();
    let mut best_score = base_score;
    let mut best_label = "llm".to_string();

    let survey_id = survey.id.to_string();
    let scout_id = scout.id.to_string();

    // attempt 4: majority swap
    let mut majority_answers = base_answers.clone();
    let majority_changes = majority_vote_swap(&mut majority_answers, &questions, VOTE_SWAP_THRESHOLD);
    if majority_changes.is_empty() {
        tracing::info!("  majority_vote_swap: no eligible swap — skip attempt 4");
    } else {
        log_swap_changes("majority", &majority_changes);
        delete_submission(pool, &base_submission_id).await?;
        fill_one_person_inner(pool, cfg, survey, scout, Some(&majority_answers)).await;
        if let Some(sub) = fetch_submission_for(pool, &survey_id, &scout_id).await? {
            let _ = mark_pathfinder(pool, &sub.id.to_string()).await;
            if let Some(s) = sub.score {
                tracing::info!("  Pathfinder majority-swap → score {}", s);
                if s == 100 {
                    tracing::info!("  Pathfinder hit 100 via majority swap — gate open");
                    return Ok(majority_answers);
                }
                if s > best_score {
                    best_score = s;
                    best_answers = majority_answers.clone();
                    best_label = "majority".to_string();
                }
            }
        }
    }

    // attempt 5: minority swap (從 base_answers 起算，與 majority 分開假設)
    let mut minority_answers = base_answers.clone();
    let minority_changes = minority_vote_swap(&mut minority_answers, &questions, VOTE_SWAP_THRESHOLD);
    if minority_changes.is_empty() {
        tracing::info!("  minority_vote_swap: no eligible swap — skip attempt 5");
    } else {
        log_swap_changes("minority", &minority_changes);
        if let Some(sub) = fetch_submission_for(pool, &survey_id, &scout_id).await? {
            delete_submission(pool, &sub.id.to_string()).await?;
        }
        fill_one_person_inner(pool, cfg, survey, scout, Some(&minority_answers)).await;
        if let Some(sub) = fetch_submission_for(pool, &survey_id, &scout_id).await? {
            let _ = mark_pathfinder(pool, &sub.id.to_string()).await;
            if let Some(s) = sub.score {
                tracing::info!("  Pathfinder minority-swap → score {}", s);
                if s == 100 {
                    tracing::info!("  Pathfinder hit 100 via minority swap — gate open");
                    return Ok(minority_answers);
                }
                if s > best_score {
                    best_score = s;
                    best_answers = minority_answers.clone();
                    best_label = "minority".to_string();
                }
            }
        }
    }

    tracing::info!(
        "  Vote-swap fallback done. Best={} score={}",
        best_label, best_score
    );

    // 終結性補救：若 surveycake 端最後一次提交分數不是 best，再做一次提交鎖住 best
    let cur_sub = fetch_submission_for(pool, &survey_id, &scout_id).await?;
    let cur_score = cur_sub.as_ref().and_then(|s| s.score).unwrap_or(-1);
    if cur_score < best_score {
        tracing::info!(
            "  Final resubmit with best ({} → {}) answers",
            cur_score, best_score
        );
        if let Some(ref sub) = cur_sub {
            delete_submission(pool, &sub.id.to_string()).await?;
        }
        fill_one_person_inner(pool, cfg, survey, scout, Some(&best_answers)).await;
        if let Some(sub) = fetch_submission_for(pool, &survey_id, &scout_id).await? {
            let _ = mark_pathfinder(pool, &sub.id.to_string()).await;
        }
    }

    tracing::warn!(
        "  Pathfinder score {} after vote-swap fallback — gate forced open",
        best_score
    );
    Ok(best_answers)
}

// ── vote-swap helpers ────────────────────────────────────────────────────────

fn options_as_strings(opts: &serde_json::Value) -> Vec<String> {
    opts.as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

fn answer_index(options: &[String], answer: &str) -> Option<usize> {
    options.iter().position(|o| o == answer)
}

/// 對每題回傳 LLM 答案落在 options 中的索引（找不到則 None）。
fn answer_indices(
    answers: &HashMap<String, String>,
    questions: &[Question],
) -> HashMap<String, Option<usize>> {
    questions
        .iter()
        .map(|q| {
            let opts = options_as_strings(&q.options);
            let idx = answers
                .get(&q.subject_id)
                .and_then(|a| answer_index(&opts, a));
            (q.subject_id.clone(), idx)
        })
        .collect()
}

/// 統計索引出現次數，回傳 (排序後 (index, count) 降冪 vec, 有效題數)。
fn index_distribution(
    indices: &HashMap<String, Option<usize>>,
) -> (Vec<(usize, usize)>, usize) {
    let mut counts: HashMap<usize, usize> = HashMap::new();
    let mut total = 0usize;
    for v in indices.values().flatten() {
        *counts.entry(*v).or_default() += 1;
        total += 1;
    }
    let mut sorted: Vec<_> = counts.into_iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    (sorted, total)
}

/// 多數派改投：眾數佔比 >= threshold 時，把所有「索引異於眾數」的題目改成眾數對應選項。
/// 回傳 [(subject_id, old_answer, new_answer)]。
fn majority_vote_swap(
    answers: &mut HashMap<String, String>,
    questions: &[Question],
    threshold: f64,
) -> Vec<(String, String, String)> {
    let indices = answer_indices(answers, questions);
    let (sorted, total) = index_distribution(&indices);
    if total == 0 || sorted.is_empty() {
        return vec![];
    }
    let (mode_idx, mode_count) = sorted[0];
    let ratio = mode_count as f64 / total as f64;
    if ratio < threshold {
        tracing::info!(
            "  majority_vote_swap: top index={} ratio={:.0}% < threshold={:.0}%",
            mode_idx,
            ratio * 100.0,
            threshold * 100.0
        );
        return vec![];
    }
    let mut changes = vec![];
    for q in questions {
        let cur_idx = indices.get(&q.subject_id).copied().flatten();
        if cur_idx == Some(mode_idx) {
            continue;
        }
        let opts = options_as_strings(&q.options);
        if let Some(new_ans) = opts.get(mode_idx).cloned() {
            let old = answers
                .insert(q.subject_id.clone(), new_ans.clone())
                .unwrap_or_default();
            changes.push((q.subject_id.clone(), old, new_ans));
        }
    }
    changes
}

/// 少數派改投：眾數佔比 >= threshold 時，從多數派群裡挑 1 題（題幹最短的那題作為 heuristic）
/// 改成「次大眾數」對應選項。每次只改 1 題，避免誤殺多題。
fn minority_vote_swap(
    answers: &mut HashMap<String, String>,
    questions: &[Question],
    threshold: f64,
) -> Vec<(String, String, String)> {
    let indices = answer_indices(answers, questions);
    let (sorted, total) = index_distribution(&indices);
    if total == 0 || sorted.len() < 2 {
        return vec![];
    }
    let (mode_idx, mode_count) = sorted[0];
    let ratio = mode_count as f64 / total as f64;
    if ratio < threshold {
        tracing::info!(
            "  minority_vote_swap: top index={} ratio={:.0}% < threshold={:.0}%",
            mode_idx,
            ratio * 100.0,
            threshold * 100.0
        );
        return vec![];
    }
    let alt_idx = sorted[1].0;

    let mut candidates: Vec<&Question> = questions
        .iter()
        .filter(|q| indices.get(&q.subject_id).copied().flatten() == Some(mode_idx))
        .collect();
    candidates.sort_by_key(|q| q.question_text.len());
    if candidates.is_empty() {
        return vec![];
    }
    let target = candidates[0];
    let opts = options_as_strings(&target.options);
    if let Some(new_ans) = opts.get(alt_idx).cloned() {
        let old = answers
            .insert(target.subject_id.clone(), new_ans.clone())
            .unwrap_or_default();
        return vec![(target.subject_id.clone(), old, new_ans)];
    }
    vec![]
}

fn log_swap_changes(label: &str, changes: &[(String, String, String)]) {
    tracing::info!(
        "  vote-swap [{}]: {} change(s)",
        label,
        changes.len()
    );
    for (sid, old, new_) in changes {
        let old_short: String = old.chars().take(40).collect();
        let new_short: String = new_.chars().take(40).collect();
        tracing::info!("    {}: {} → {}", sid, old_short, new_short);
    }
}

async fn fetch_questions(pool: &SqlitePool, survey_id: &str) -> Result<Vec<Question>> {
    let rows = sqlx::query_as::<_, Question>(
        "SELECT id, survey_id, subject_id, question_text, options, \
                correct_answer, verified, created_at \
         FROM questions WHERE survey_id = ? ORDER BY subject_id",
    )
    .bind(survey_id)
    .fetch_all(pool)
    .await
    .context("fetch questions")?;
    Ok(rows)
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
