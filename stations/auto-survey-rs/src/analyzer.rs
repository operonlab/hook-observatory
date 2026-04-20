//! analyzer.rs — LiteLLM quiz analysis (Phase 3a).
//!
//! Mirrors `analyzer.py`:
//!   - `analyze_quiz`      → basic prompt, stores correct_answer per question
//!   - `analyze_quiz_rlm`  → enhanced reasoning prompt, returns structured JSON
//!   - `reanalyze_wrong`   → re-ask only questions answered incorrectly

use anyhow::{anyhow, Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;
use std::collections::HashMap;
use std::time::Duration;
use uuid::Uuid;

use crate::config::Settings;
use crate::models::Question;

// ---------------------------------------------------------------------------
// Prompt constants — byte-for-byte matches Python `_build_prompt` header
// ---------------------------------------------------------------------------

const PROMPT_HEADER: &str = "你是測驗分析專家。以下是線上測驗的選擇題。\n請分析每題的正確答案，只回傳選項字母（A/B/C/D）。\n\n以純 JSON 格式回答（不要 markdown code fence）：\n{\"answers\": [{\"subject_id\": \"subject-5\", \"answer\": \"C\"}, ...]}\n\n題目：";

const REANALYZE_HEADER: &str = "以下測驗題目之前答錯了，請重新仔細分析正確答案。\n注意：之前的答案是錯的，請重新思考。\n只回傳選項字母（A/B/C/D）。\n\n以純 JSON 格式回答（不要 markdown code fence）：\n{\"answers\": [{\"subject_id\": \"subject-5\", \"answer\": \"C\"}, ...]}";

const RLM_PROMPT_TEMPLATE: &str = "你是測驗分析專家。請對以下測驗題目進行深度分析：\n\n1. **answers**: 分析每題正確答案 {subject_id: answer_text}\n2. **topic_groups**: 將題目按主題分組 [{topic: str, subject_ids: [str]}]\n3. **justifications**: 每題的答案理由 {subject_id: justification_text}\n4. **cross_validation**: 交叉驗證——找出題目之間可能矛盾或互相佐證的關係 [{subjects: [str], relationship: str, note: str}]\n\n以 JSON 格式回覆完整結果。FINAL() 包住你的 JSON。";

// ---------------------------------------------------------------------------
// HTTP request / response shapes
// ---------------------------------------------------------------------------

#[derive(Serialize)]
struct ChatRequest<'a> {
    model: &'a str,
    messages: Vec<ChatMessage<'a>>,
    temperature: f32,
}

#[derive(Serialize)]
struct ChatMessage<'a> {
    role: &'a str,
    content: &'a str,
}

#[derive(Deserialize)]
struct ChatResponse {
    choices: Vec<Choice>,
}

#[derive(Deserialize)]
struct Choice {
    message: MessageContent,
}

#[derive(Deserialize)]
struct MessageContent {
    content: String,
}

// ---------------------------------------------------------------------------
// Transient-error detection (mirrors Python `is_transient_error`)
// ---------------------------------------------------------------------------

fn is_transient_reqwest_error(e: &reqwest::Error) -> bool {
    // HTTP 5xx
    if let Some(status) = e.status() {
        if status.is_server_error() {
            return true;
        }
    }
    // Connection / timeout / request-level errors
    e.is_connect() || e.is_timeout() || e.is_request()
}

/// Public transient-error detector mirroring Python `is_transient_error`.
/// Walks the anyhow error cause chain looking for a reqwest::Error we
/// consider transient (5xx / connect / timeout / request-level).
pub fn is_transient_error(e: &anyhow::Error) -> bool {
    for cause in e.chain() {
        if let Some(re) = cause.downcast_ref::<reqwest::Error>() {
            if is_transient_reqwest_error(re) {
                return true;
            }
        }
    }
    false
}

/// Exponential backoff: 1, 2, 4, 8, 16 … capped at 16s
fn backoff_secs(attempt: u32) -> u64 {
    std::cmp::min(2u64.pow(attempt - 1), 16)
}

// ---------------------------------------------------------------------------
// Core LiteLLM call with retry + exponential backoff
// ---------------------------------------------------------------------------

async fn call_litellm(prompt: &str, cfg: &Settings) -> Result<String> {
    let max_attempts: u32 = 5;
    let mut last_err: Option<anyhow::Error> = None;

    for attempt in 1..=max_attempts {
        // Build a **new** client each attempt to discard stale keepalive connections
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(60))
            .build()
            .context("build reqwest client")?;

        let url = format!("{}/chat/completions", cfg.litellm_base_url);
        let body = ChatRequest {
            model: &cfg.llm_model,
            messages: vec![ChatMessage { role: "user", content: prompt }],
            temperature: 0.1,
        };

        tracing::info!(
            "[analyze] LiteLLM model={} attempt={}/{}",
            cfg.llm_model,
            attempt,
            max_attempts
        );

        match client
            .post(&url)
            .header("Authorization", format!("Bearer {}", cfg.litellm_api_key))
            .json(&body)
            .send()
            .await
        {
            Ok(resp) => {
                if resp.status().is_server_error() {
                    let status = resp.status();
                    let backoff = backoff_secs(attempt);
                    tracing::warn!(
                        "[analyze] HTTP {} — retry in {}s (attempt {}/{})",
                        status,
                        backoff,
                        attempt,
                        max_attempts
                    );
                    last_err = Some(anyhow!("HTTP {}", status));
                    if attempt < max_attempts {
                        tokio::time::sleep(Duration::from_secs(backoff)).await;
                    }
                    continue;
                }

                let chat: ChatResponse = resp
                    .json()
                    .await
                    .context("deserialize LiteLLM response")?;

                return Ok(chat
                    .choices
                    .into_iter()
                    .next()
                    .ok_or_else(|| anyhow!("empty choices"))?
                    .message
                    .content);
            }
            Err(e) => {
                let transient = is_transient_reqwest_error(&e);
                last_err = Some(anyhow!(e));
                if !transient || attempt == max_attempts {
                    return Err(last_err.unwrap());
                }
                let backoff = backoff_secs(attempt);
                tracing::warn!(
                    "[analyze] Transient error — retry in {}s (attempt {}/{})",
                    backoff,
                    attempt,
                    max_attempts
                );
                tokio::time::sleep(Duration::from_secs(backoff)).await;
            }
        }
    }

    Err(last_err.unwrap_or_else(|| anyhow!("LiteLLM exhausted retries")))
}

// ---------------------------------------------------------------------------
// Prompt builders
// ---------------------------------------------------------------------------

/// Mirror Python `_build_prompt(questions)` exactly.
pub fn build_prompt(questions: &[Question]) -> String {
    let mut lines = vec![PROMPT_HEADER.to_string()];
    for q in questions {
        let opts: Vec<String> = match &q.options {
            serde_json::Value::Array(arr) => {
                arr.iter().filter_map(|v| v.as_str().map(String::from)).collect()
            }
            _ => vec![],
        };
        lines.push(format!("\n{}: {}", q.subject_id, q.question_text));
        for (i, opt) in opts.iter().enumerate() {
            let letter = char::from(b'A' + i as u8);
            lines.push(format!("  {}. {}", letter, opt));
        }
    }
    lines.join("\n")
}

/// Prompt for `reanalyze_wrong`.
fn build_reanalyze_prompt(questions: &[Question]) -> String {
    let mut lines = vec![REANALYZE_HEADER.to_string(), String::new()];
    for q in questions {
        let opts: Vec<String> = match &q.options {
            serde_json::Value::Array(arr) => {
                arr.iter().filter_map(|v| v.as_str().map(String::from)).collect()
            }
            _ => vec![],
        };
        lines.push(format!("\n{}: {}", q.subject_id, q.question_text));
        if let Some(ref prev) = q.correct_answer {
            lines.push(format!("  之前錯誤的答案：{}", prev));
        }
        for (i, opt) in opts.iter().enumerate() {
            let letter = char::from(b'A' + i as u8);
            lines.push(format!("  {}. {}", letter, opt));
        }
    }
    lines.join("\n")
}

// ---------------------------------------------------------------------------
// Answer parsing helpers — mirror Python `_strip_letter_prefix` /
// `_resolve_letter_to_option` / `_parse_answers`
// ---------------------------------------------------------------------------

/// Strip "A. ", "B. " prefix (Python `_strip_letter_prefix`).
pub fn strip_letter_prefix(text: &str) -> String {
    let re = Regex::new(r"^[A-Z]\.\s*").unwrap();
    re.replace(text, "").to_string()
}

/// Resolve a letter (A/B/C/D) to the full option text (Python `_resolve_letter_to_option`).
pub fn resolve_letter_to_option(answer: &str, options: &[String]) -> String {
    let stripped = answer.trim();

    // Single letter "A" – "H"
    if stripped.len() == 1 {
        if let Some(c) = stripped.chars().next() {
            let upper = c.to_ascii_uppercase();
            if upper.is_ascii_uppercase() && upper >= 'A' && upper <= 'H' {
                let idx = (upper as u8 - b'A') as usize;
                if idx < options.len() {
                    return options[idx].clone();
                }
            }
        }
    }

    // "A." or "B. " pattern
    let re_dot = Regex::new(r"^([A-H])\.\s*$").unwrap();
    if let Some(cap) = re_dot.captures(stripped) {
        let c = cap[1].chars().next().unwrap().to_ascii_uppercase();
        let idx = (c as u8 - b'A') as usize;
        if idx < options.len() {
            return options[idx].clone();
        }
    }

    // Fallback — full text, strip prefix
    strip_letter_prefix(stripped)
}

/// Parse LLM raw output into `{subject_id -> answer_text}` (mirrors `_parse_answers`).
pub fn parse_answers(raw: &str, questions: &[Question]) -> Result<HashMap<String, String>> {
    // Strip markdown fences
    let re_fence = Regex::new(r"```(?:json)?\s*").unwrap();
    let re_fence_end = Regex::new(r"```\s*").unwrap();
    let cleaned = re_fence.replace_all(raw, "");
    let cleaned = re_fence_end.replace_all(&cleaned, "");

    // Find JSON object
    let re_obj = Regex::new(r"(?s)\{.*\}").unwrap();
    let json_str = re_obj
        .find(&cleaned)
        .ok_or_else(|| anyhow!("No JSON found in LLM response: {}", &raw[..raw.len().min(300)]))?
        .as_str();

    // Fix invalid JSON escapes (LaTeX like \log, \Sigma)
    let re_invalid_escape = Regex::new(r#"\\(?!["\\/bfnrtu])"#).unwrap();
    let json_str = re_invalid_escape.replace_all(json_str, "\\\\");

    let data: serde_json::Value =
        serde_json::from_str(&json_str).context("parse LLM JSON response")?;

    // Build question lookup
    let q_lookup: HashMap<String, Vec<String>> = questions
        .iter()
        .map(|q| {
            let opts: Vec<String> = match &q.options {
                serde_json::Value::Array(arr) => {
                    arr.iter().filter_map(|v| v.as_str().map(String::from)).collect()
                }
                _ => vec![],
            };
            (q.subject_id.clone(), opts)
        })
        .collect();

    let resolve = |subject_id: &str, answer: &str| -> String {
        if let Some(opts) = q_lookup.get(subject_id) {
            if !opts.is_empty() {
                return resolve_letter_to_option(answer, opts);
            }
        }
        strip_letter_prefix(answer)
    };

    // {"answers": [...]} format
    if let Some(answers_arr) = data.get("answers").and_then(|v| v.as_array()) {
        return Ok(answers_arr
            .iter()
            .filter_map(|a| {
                let sid = a.get("subject_id")?.as_str()?;
                let ans = a.get("answer")?.as_str()?;
                Some((sid.to_string(), resolve(sid, ans)))
            })
            .collect());
    }

    // Flat {"subject-5": "C", ...} format
    if let Some(obj) = data.as_object() {
        return Ok(obj
            .iter()
            .filter(|(k, _)| k.starts_with("subject-"))
            .filter_map(|(k, v)| {
                let ans = v.as_str()?;
                Some((k.clone(), resolve(k, ans)))
            })
            .collect());
    }

    Err(anyhow!("Unexpected JSON structure: {}", &raw[..raw.len().min(300)]))
}

// ---------------------------------------------------------------------------
// DB helpers (runtime queries — no compile-time DATABASE_URL needed)
// ---------------------------------------------------------------------------

async fn fetch_questions_for_survey(
    pool: &SqlitePool,
    survey_id: &str,
) -> Result<Vec<Question>> {
    let rows = sqlx::query_as::<_, Question>(
        "SELECT id, survey_id, subject_id, question_text, options, \
                correct_answer, verified, created_at \
         FROM questions \
         WHERE survey_id = ? \
         ORDER BY subject_id",
    )
    .bind(survey_id)
    .fetch_all(pool)
    .await
    .context("fetch questions")?;
    Ok(rows)
}

async fn update_correct_answer(pool: &SqlitePool, question_id: &str, answer: &str) -> Result<()> {
    sqlx::query("UPDATE questions SET correct_answer = ? WHERE id = ?")
        .bind(answer)
        .bind(question_id)
        .execute(pool)
        .await
        .context("update correct_answer")?;
    Ok(())
}

async fn update_reanalyzed_answer(
    pool: &SqlitePool,
    question_id: &str,
    answer: &str,
) -> Result<()> {
    sqlx::query("UPDATE questions SET correct_answer = ?, verified = FALSE WHERE id = ?")
        .bind(answer)
        .bind(question_id)
        .execute(pool)
        .await
        .context("update reanalyzed answer")?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Analyze all quiz questions for a survey. Stores `correct_answer` in DB.
///
/// Mirrors Python `analyze_quiz(db, survey)`.
pub async fn analyze_quiz(
    pool: &SqlitePool,
    survey_id: Uuid,
    cfg: &Settings,
) -> Result<HashMap<String, String>> {
    let sid = survey_id.to_string();
    let questions = fetch_questions_for_survey(pool, &sid).await?;

    if questions.is_empty() {
        return Ok(HashMap::new());
    }

    // Already fully analyzed?
    let existing: HashMap<String, String> = questions
        .iter()
        .filter_map(|q| q.correct_answer.as_ref().map(|a| (q.subject_id.clone(), a.clone())))
        .collect();
    if existing.len() == questions.len() {
        return Ok(existing);
    }

    let prompt = build_prompt(&questions);
    let raw = call_litellm(&prompt, cfg).await?;
    let answers = parse_answers(&raw, &questions)?;

    // Persist to DB
    for q in &questions {
        if let Some(ans) = answers.get(&q.subject_id) {
            update_correct_answer(pool, &q.id.to_string(), ans).await?;
        }
    }

    Ok(answers)
}

/// Enhanced RLM analysis. Falls back to basic `analyze_quiz` on error.
///
/// Mirrors Python `analyze_quiz_rlm(db, survey)`.
pub async fn analyze_quiz_rlm(
    pool: &SqlitePool,
    survey_id: Uuid,
    cfg: &Settings,
) -> Result<serde_json::Value> {
    let sid = survey_id.to_string();
    let questions = fetch_questions_for_survey(pool, &sid).await?;

    if questions.is_empty() {
        return Ok(serde_json::json!({
            "answers": {},
            "topic_groups": [],
            "justifications": {},
            "cross_validation": []
        }));
    }

    // Build context JSON for the prompt
    let q_data: Vec<serde_json::Value> = questions
        .iter()
        .map(|q| {
            serde_json::json!({
                "subject_id": q.subject_id,
                "question_text": q.question_text,
                "options": q.options,
                "current_answer": q.correct_answer.clone().unwrap_or_default(),
            })
        })
        .collect();

    let context_str =
        serde_json::to_string_pretty(&q_data).unwrap_or_else(|_| "[]".to_string());

    let prompt = format!("{}\n\n{}", RLM_PROMPT_TEMPLATE, context_str);

    // Fallback: run basic analyze_quiz
    async fn fallback(
        pool: &SqlitePool,
        survey_id: Uuid,
        cfg: &Settings,
    ) -> serde_json::Value {
        let basic = analyze_quiz(pool, survey_id, cfg).await.unwrap_or_default();
        serde_json::json!({
            "answers": basic,
            "topic_groups": [],
            "justifications": {},
            "cross_validation": [],
            "_fallback": true
        })
    }

    let raw = match call_litellm(&prompt, cfg).await {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!("[analyze_rlm] LLM call failed: {e} — falling back");
            return Ok(fallback(pool, survey_id, cfg).await);
        }
    };

    // Strip fences
    let re_fence = Regex::new(r"```(?:json)?\s*").unwrap();
    let re_fence_end = Regex::new(r"```\s*").unwrap();
    let cleaned = re_fence.replace_all(&raw, "");
    let cleaned = re_fence_end.replace_all(&cleaned, "");

    let re_obj = Regex::new(r"(?s)\{.*\}").unwrap();
    let json_str = match re_obj.find(&cleaned) {
        Some(m) => m.as_str().to_string(),
        None => {
            tracing::warn!("[analyze_rlm] No JSON in response — fallback");
            return Ok(fallback(pool, survey_id, cfg).await);
        }
    };

    let data: serde_json::Value = match serde_json::from_str(&json_str) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("[analyze_rlm] JSON parse error: {e} — fallback");
            return Ok(fallback(pool, survey_id, cfg).await);
        }
    };

    // Normalize answers (list or object)
    let answers: HashMap<String, String> = match data.get("answers") {
        Some(serde_json::Value::Array(arr)) => arr
            .iter()
            .filter_map(|a| {
                let sid = a.get("subject_id")?.as_str()?.to_string();
                let ans = a.get("answer")?.as_str()?.to_string();
                Some((sid, ans))
            })
            .collect(),
        Some(serde_json::Value::Object(map)) => map
            .iter()
            .filter_map(|(k, v)| Some((k.clone(), v.as_str()?.to_string())))
            .collect(),
        _ => HashMap::new(),
    };

    // Persist
    for q in &questions {
        if let Some(ans) = answers.get(&q.subject_id) {
            update_correct_answer(pool, &q.id.to_string(), ans).await?;
        }
    }

    Ok(serde_json::json!({
        "answers": answers,
        "topic_groups": data.get("topic_groups").cloned().unwrap_or(serde_json::json!([])),
        "justifications": data.get("justifications").cloned().unwrap_or(serde_json::json!({})),
        "cross_validation": data.get("cross_validation").cloned().unwrap_or(serde_json::json!([])),
    }))
}

/// Re-analyze questions that the pathfinder answered incorrectly.
///
/// Mirrors Python `reanalyze_wrong(db, survey, wrong_subjects)`.
pub async fn reanalyze_wrong(
    pool: &SqlitePool,
    survey_id: Uuid,
    wrong_subjects: &[String],
    cfg: &Settings,
) -> Result<HashMap<String, String>> {
    if wrong_subjects.is_empty() {
        return Ok(HashMap::new());
    }

    let sid = survey_id.to_string();

    // Build dynamic IN clause
    let placeholders = wrong_subjects.iter().map(|_| "?").collect::<Vec<_>>().join(", ");
    let sql = format!(
        "SELECT id, survey_id, subject_id, question_text, options, \
                correct_answer, verified, created_at \
         FROM questions \
         WHERE survey_id = ? AND subject_id IN ({})",
        placeholders
    );

    let mut q = sqlx::query_as::<_, Question>(&sql).bind(&sid);
    for ws in wrong_subjects {
        q = q.bind(ws);
    }
    let questions: Vec<Question> = q.fetch_all(pool).await.context("fetch wrong questions")?;

    if questions.is_empty() {
        return Ok(HashMap::new());
    }

    let prompt = build_reanalyze_prompt(&questions);
    let raw = call_litellm(&prompt, cfg).await?;
    let answers = parse_answers(&raw, &questions)?;

    for q in &questions {
        if let Some(ans) = answers.get(&q.subject_id) {
            update_reanalyzed_answer(pool, &q.id.to_string(), ans).await?;
        }
    }

    Ok(answers)
}
