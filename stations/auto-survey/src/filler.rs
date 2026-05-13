//! Phase 3: Fill — generate JS fill scripts and submit forms.
//! Mirrors Python `filler.py` line-for-line.

use crate::models::{Person, Submission, Survey};
use crate::playwright::{to_camoufox_js, BrowserSession};
use anyhow::{Context, Result};
use regex::Regex;
use serde_json::Value;
use sqlx::SqlitePool;
use std::collections::HashMap;
use uuid::Uuid;

// ── JS building ───────────────────────────────────────────────────────────────

/// Escape a string for use inside a JavaScript single-quoted string.
/// Mirrors Python `_js_escape(s)`.
pub fn js_escape(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('\n', "\\n")
}

/// Generate the fill script in Playwright async (page) => format.
/// Will be converted to camoufox format via `to_camoufox_js()`.
/// Mirrors Python `_build_fill_script(person, survey, answers)`.
pub fn build_fill_script(
    person: &Person,
    survey: &Survey,
    answers: Option<&HashMap<String, String>>,
) -> String {
    let company = &person.company;
    let empty_vec: Vec<Value> = vec![];
    let company_options: Vec<String> = survey
        .company_options
        .as_ref()
        .and_then(|v| v.as_array())
        .unwrap_or(&empty_vec)
        .iter()
        .filter_map(|v| v.as_str().map(|s| s.to_owned()))
        .collect();

    // Determine company selection strategy
    let (company_click, company_fill) = if company_options.contains(company) {
        let click = format!(
            r#"await page.locator('[data-qa="option-{}"]').first().click();"#,
            js_escape(company)
        );
        (click, String::new())
    } else {
        // Select "其他" and fill text input
        let click = r#"await page.locator('[data-qa="option-其他"]').first().click();"#.to_string();
        let fill = format!(
            r#"
    await page.waitForTimeout(500);
    const otherInput = page.locator('[data-qa="subject-2"] input, [data-qa="subject-2"] textarea, [data-qa="subject-1"] input').first();
    if (await otherInput.count() > 0) {{
      await otherInput.fill('{}');
    }}"#,
            js_escape(company)
        );
        (click, fill)
    };

    // Build answer clicks for quiz
    let mut answer_clicks = String::new();
    if let Some(ans_map) = answers {
        for (subject_id, answer_text) in ans_map {
            let escaped = js_escape(answer_text);
            answer_clicks.push_str(&format!(
                r#"
    await page.evaluate(() => {{
      const subj = document.querySelector('[data-qa="{subject_id}"]');
      if (!subj) return;
      const opts = subj.querySelectorAll('[data-qa^="option-"]');
      let clicked = false;
      for (const opt of opts) {{
        const qa = opt.getAttribute('data-qa');
        if (qa === 'option-{escaped}') {{
          opt.click();
          clicked = true;
          break;
        }}
      }}
      if (!clicked) {{
        const needle = '{escaped}'.replace(/\s+/g, '');
        for (const opt of opts) {{
          const qa = (opt.getAttribute('data-qa')) || '';
          const optText = qa.replace('option-', '').replace(/\s+/g, '');
          if (optText && (optText.includes(needle) || needle.includes(optText))) {{
            opt.click();
            clicked = true;
            break;
          }}
        }}
      }}
    }});
    await page.waitForTimeout(300);"#
            ));
        }
    }

    let name_escaped = js_escape(&person.name);
    let email_escaped = js_escape(&person.email);

    format!(
        r#"async (page) => {{
    // 0. Wait for React render
    await page.waitForTimeout(3000);

    // 1. Select company
    {company_click}
    {company_fill}
    await page.waitForTimeout(200);

    // 2. Fill name (subject-3) + email (subject-4)
    const nameField = page.locator('[data-qa="subject-3"] input, [data-qa="subject-3"] textarea').first();
    if (await nameField.count() > 0) {{
      await nameField.fill('{name_escaped}');
    }}
    await page.waitForTimeout(100);

    const emailField = page.locator('[data-qa="subject-4"] input, [data-qa="subject-4"] textarea').first();
    if (await emailField.count() > 0) {{
      await emailField.fill('{email_escaped}');
    }}
    await page.waitForTimeout(100);

    // 3. Answer quiz questions (if any)
    {answer_clicks}

    // 4. Consent checkbox
    const consent = page.locator('[data-qa*="本人已詳閱"], [data-qa*="同意"]').first();
    if (await consent.count() > 0) {{
      await consent.click();
      await page.waitForTimeout(200);
    }}

    // 5. Random delay before submit (simulate human)
    const delay = Math.floor(Math.random() * 1500) + 500;
    await page.waitForTimeout(delay);

    // 6. Submit
    await page.locator('text=送出').first().click();
    await page.waitForTimeout(500);

    // 7. Handle confirmation dialog
    const preSubmitUrl = page.url();
    const confirmBtns = ['text=確定送出', 'text=確定', 'text=確認', 'text=OK'];
    for (const sel of confirmBtns) {{
      const btn = page.locator(sel).first();
      if (await btn.count() > 0 && await btn.isVisible()) {{
        await btn.click();
        break;
      }}
    }}

    // 8. Wait for form to unmount OR result text appears.
    // (SurveyCake quiz does NOT change URL after submit; waiting for URL change
    // burns 30s every time. Watch for the success indicator instead.)
    try {{
      await page.waitForFunction(
        () => {{
          const t = document.body.innerText;
          return /成績|分數|Score|感謝|你的|本次/.test(t)
            || !document.querySelector('[data-qa^="subject-"]');
        }},
        null,
        {{ timeout: 30000 }}
      );
    }} catch (e) {{}}

    // 9. Wait for result page to fully load
    try {{
      await page.waitForLoadState('networkidle', {{ timeout: 15000 }});
    }} catch (e) {{}}
    await page.waitForTimeout(3000);

    // 10. Wait for score text to appear (quiz result pages)
    try {{
      await page.waitForFunction(
        () => /成績|分數|Score|感謝|你的/.test(document.body.innerText),
        null,
        {{ timeout: 15000 }}
      );
    }} catch (e) {{}}
    // Extra wait for score rendering after text appears
    await page.waitForTimeout(2000);

    // 11. Extract page text
    const bodyText = await page.evaluate(() => document.body.innerText);
    return bodyText;
  }}"#
    )
}

// ── Score extraction ──────────────────────────────────────────────────────────

/// Extract score from post-submission page text.
/// Mirrors Python `_extract_score(page_text)`.
pub fn extract_score(page_text: &str) -> Option<i32> {
    let patterns = [
        r"成績[為是]?\s*[:：]?\s*(\d+)",
        r"分數[為是]?\s*[:：]?\s*(\d+)",
        r"得到\s*(\d+)\s*分",
        r"(\d+)\s*分",
        r"Score\s*[:：]?\s*(\d+)",
    ];
    for pat in &patterns {
        if let Ok(re) = Regex::new(pat) {
            if let Some(cap) = re.captures(page_text) {
                if let Ok(score) = cap[1].parse::<i32>() {
                    if (0..=100).contains(&score) {
                        return Some(score);
                    }
                }
            }
        }
    }
    None
}

// ── fill_form ─────────────────────────────────────────────────────────────────

/// Fill the form for one person. Returns the Submission record.
/// Mirrors Python `fill_form(pw, db, survey, person, answers) -> Submission`.
pub async fn fill_form(
    pw: &dyn BrowserSession,
    pool: &SqlitePool,
    survey: &Survey,
    person: &Person,
    answers: Option<&HashMap<String, String>>,
) -> Result<Submission> {
    let survey_id_str = survey.id.to_string();
    let person_id_str = person.id.to_string();

    // Check if already submitted successfully
    let existing = fetch_submission(pool, &survey_id_str, &person_id_str).await?;
    if let Some(ref sub) = existing {
        if sub.status == "success" {
            return Ok(sub.clone());
        }
    }

    let script = build_fill_script(person, survey, answers);
    let adapted_js = if pw.backend() == "camoufox" {
        to_camoufox_js(&script)
    } else {
        script.clone()
    };

    let now = chrono::Utc::now();

    match try_fill(pw, survey, &adapted_js).await {
        Ok((result_text, score)) => {
            // Detect silent submission failure (still on form page)
            let form_still_visible = ["此題必填", "送出", "請選擇公司名稱"]
                .iter()
                .any(|&m| result_text.contains(m));

            if form_still_visible && survey.survey_type == "quiz" {
                tracing::warn!(
                    "[fill] {} form still visible — submission likely failed",
                    person.name
                );
            } else if survey.survey_type == "quiz" && score.is_none() {
                let preview = result_text.chars().take(300).collect::<String>();
                tracing::warn!(
                    "[fill] {} score=None — regex matched nothing. preview={}",
                    person.name,
                    preview.replace('\n', " | ")
                );
            }

            let answers_json: Option<Value> = answers.map(|m| serde_json::to_value(m).unwrap_or(Value::Null));
            let answers_str = answers_json.as_ref().map(|v| v.to_string());

            let (status, error_message, final_score) = if form_still_visible
                && survey.survey_type == "quiz"
            {
                (
                    "failed",
                    Some("Form submission failed — still on form page".to_string()),
                    None,
                )
            } else {
                ("success", None, score)
            };

            upsert_submission(
                pool,
                existing.as_ref(),
                &survey_id_str,
                &person_id_str,
                status,
                final_score,
                false,
                answers_str.as_deref(),
                error_message.as_deref(),
                now,
            )
            .await
        }
        Err(e) => {
            let err_str = format!("{e}")[..500.min(format!("{e}").len())].to_string();
            upsert_submission(
                pool,
                existing.as_ref(),
                &survey_id_str,
                &person_id_str,
                "failed",
                None,
                false,
                None,
                Some(&err_str),
                now,
            )
            .await
        }
    }
}

/// Open page, run fill JS, parse result. Returns (result_text, score).
async fn try_fill(
    pw: &dyn BrowserSession,
    survey: &Survey,
    adapted_js: &str,
) -> Result<(String, Option<i32>)> {
    pw.open(&survey.url).await?;
    let raw_output = pw.run_code(adapted_js, 90).await?;

    let result_text = raw_output.trim().to_string();

    // Strip Playwright "### Result" wrapper
    let result_text = if result_text.contains("### Result") {
        let re = Regex::new(r"### Result\s*\n(.*?)(?:\n###|\z)").unwrap();
        if let Some(cap) = re.captures(&result_text) {
            cap[1].trim().trim_matches('"').to_string()
        } else {
            result_text
        }
    } else {
        result_text
    };

    let score = if survey.survey_type == "quiz" {
        extract_score(&result_text)
    } else {
        None
    };

    Ok((result_text, score))
}

// ── DB helpers ────────────────────────────────────────────────────────────────

async fn fetch_submission(
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
            id: Uuid::parse_str(&r.id)
                .with_context(|| format!("invalid UUID in submissions.id: {}", r.id))?,
            survey_id: Uuid::parse_str(&r.survey_id)
                .with_context(|| format!("invalid UUID in submissions.survey_id: {}", r.survey_id))?,
            person_id: Uuid::parse_str(&r.person_id)
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

#[allow(clippy::too_many_arguments)]
async fn upsert_submission(
    pool: &SqlitePool,
    existing: Option<&Submission>,
    survey_id: &str,
    person_id: &str,
    status: &str,
    score: Option<i32>,
    is_pathfinder: bool,
    answers_snapshot: Option<&str>,
    error_message: Option<&str>,
    now: chrono::DateTime<chrono::Utc>,
) -> Result<Submission> {
    let pathfinder_int = is_pathfinder as i64;

    if let Some(sub) = existing {
        let sub_id = sub.id.to_string();
        sqlx::query!(
            "UPDATE submissions SET status=?, score=?, is_pathfinder=?, answers_snapshot=?, error_message=?, submitted_at=? WHERE id=?",
            status, score, pathfinder_int, answers_snapshot, error_message, now, sub_id
        )
        .execute(pool)
        .await?;
    } else {
        let new_id = Uuid::new_v4().to_string();
        sqlx::query!(
            "INSERT INTO submissions (id, survey_id, person_id, status, score, is_pathfinder, answers_snapshot, error_message, submitted_at) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            new_id, survey_id, person_id, status, score, pathfinder_int, answers_snapshot, error_message, now
        )
        .execute(pool)
        .await?;
    }

    // Fetch back the row
    let row = fetch_submission(pool, survey_id, person_id).await?;
    row.ok_or_else(|| anyhow::anyhow!("submission not found after upsert"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_js_escape() {
        assert_eq!(js_escape("it's"), "it\\'s");
        assert_eq!(js_escape("line\nnew"), "line\\nnew");
        assert_eq!(js_escape("back\\slash"), "back\\\\slash");
    }

    #[test]
    fn test_extract_score_patterns() {
        assert_eq!(extract_score("你的成績是：80分"), Some(80));
        assert_eq!(extract_score("分數: 95"), Some(95));
        assert_eq!(extract_score("得到 100 分"), Some(100));
        assert_eq!(extract_score("Score: 70"), Some(70));
        assert_eq!(extract_score("沒有分數的頁面"), None);
        // Out of range
        assert_eq!(extract_score("今天是 2024 年"), None);
    }

    #[test]
    fn test_build_fill_script_contains_name() {
        let person = Person {
            id: Uuid::new_v4(),
            name: "張三".to_string(),
            email: "zhang@example.com".to_string(),
            company: "A公司".to_string(),
            active: true,
            created_at: chrono::Utc::now(),
        };
        let survey = Survey {
            id: Uuid::new_v4(),
            url: "https://www.surveycake.com/s/test".to_string(),
            url_hash: "abc".to_string(),
            title: Some("Test".to_string()),
            survey_type: "attendance".to_string(),
            raw_content: None,
            company_options: Some(serde_json::json!(["A公司", "B公司"])),
            created_at: chrono::Utc::now(),
        };
        let script = build_fill_script(&person, &survey, None);
        assert!(script.contains("張三"));
        assert!(script.contains("zhang@example.com"));
        assert!(script.contains(r#"option-A公司"#));
    }

    #[test]
    fn test_build_fill_script_other_company() {
        let person = Person {
            id: Uuid::new_v4(),
            name: "李四".to_string(),
            email: "li@test.com".to_string(),
            company: "C公司".to_string(), // not in options
            active: true,
            created_at: chrono::Utc::now(),
        };
        let survey = Survey {
            id: Uuid::new_v4(),
            url: "https://www.surveycake.com/s/test".to_string(),
            url_hash: "abc".to_string(),
            title: None,
            survey_type: "attendance".to_string(),
            raw_content: None,
            company_options: Some(serde_json::json!(["A公司", "B公司"])),
            created_at: chrono::Utc::now(),
        };
        let script = build_fill_script(&person, &survey, None);
        assert!(script.contains("option-其他"));
        assert!(script.contains("C公司"));
    }
}
