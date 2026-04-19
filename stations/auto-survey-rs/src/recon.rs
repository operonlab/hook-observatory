//! Phase 1: Recon — extract form structure from SurveyCake URL.
//! Mirrors Python `recon.py` line-for-line.

use crate::models::{Question, Survey};
use crate::playwright::{to_camoufox_js, BrowserSession};
use anyhow::{bail, Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use md5::{Digest, Md5};
use sqlx::SqlitePool;
use tokio::time::{sleep, Duration};
use uuid::Uuid;

// ── Extraction JS ─────────────────────────────────────────────────────────────

/// Playwright-format JS to extract full form structure from a SurveyCake page.
/// Python version uses this as EXTRACT_JS then runs `adapt_js_for_backend()` on it.
const EXTRACT_JS: &str = r#"async (page) => {
  await page.waitForTimeout(3000);

  const title = await page.evaluate(() => {
    return document.title.replace(/ » SurveyCake$/, '').trim();
  });

  const subjects = await page.evaluate(() => {
    const items = document.querySelectorAll('[data-qa]');
    const subjects = [];
    let currentSubject = null;

    for (const el of items) {
      const qa = el.getAttribute('data-qa');
      if (qa.startsWith('subject-') && !qa.startsWith('subject-type-')) {
        if (currentSubject) subjects.push(currentSubject);
        const numMatch = qa.match(/subject-(\d+)/);
        currentSubject = {
          id: qa,
          num: numMatch ? parseInt(numMatch[1]) : 0,
          text: el.innerText.replace(/^\d+\n/, '').split('\n')[0].trim(),
          fullText: el.innerText.trim(),
          type: 'unknown',
          options: [],
          hasInput: false
        };
      } else if (qa.startsWith('option-') && currentSubject) {
        currentSubject.options.push(qa.replace('option-', ''));
        currentSubject.type = 'radio';
      } else if (qa.startsWith('subject-type-') && currentSubject) {
        if (qa.includes('TXTSHORT') || qa.includes('TXTLONG')) {
          currentSubject.hasInput = true;
          if (currentSubject.options.length === 0) currentSubject.type = 'text';
        }
      }
    }
    if (currentSubject) subjects.push(currentSubject);
    return subjects;
  });

  const bodyText = await page.evaluate(() => document.body.innerText);
  return JSON.stringify({ title, subjects, bodyText });
}"#;

// ── Subject / Structure types ─────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Subject {
    pub id: String,
    pub num: i64,
    pub text: String,
    #[serde(rename = "fullText")]
    pub full_text: String,
    #[serde(rename = "type")]
    pub subject_type: String, // "radio" | "text" | "unknown"
    pub options: Vec<String>,
    #[serde(rename = "hasInput")]
    pub has_input: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SurveyStructure {
    pub title: Option<String>,
    pub subjects: Vec<Subject>,
    #[serde(rename = "bodyText")]
    pub body_text: Option<String>,
}

#[derive(Debug, Clone)]
pub struct Classified {
    pub company: Option<Subject>,
    pub name: Option<Subject>,
    pub email: Option<Subject>,
    pub consent: Option<Subject>,
    pub questions: Vec<Subject>,
}

// ── recon_survey ──────────────────────────────────────────────────────────────

/// Open URL, wait for React render, extract form structure.
/// Mirrors Python `recon_survey(pw, url) -> dict`.
pub async fn recon_survey(pw: &dyn BrowserSession, url: &str) -> Result<SurveyStructure> {
    pw.open(url).await?;
    // Python does time.sleep(3) after open (open() itself sleeps 2s, plus 1 more here)
    sleep(Duration::from_secs(1)).await;

    // Adapt EXTRACT_JS for camoufox backend
    let adapted_js = if pw.backend() == "camoufox" {
        to_camoufox_js(EXTRACT_JS)
    } else {
        EXTRACT_JS.to_string()
    };

    let raw = pw.run_code(&adapted_js, 30).await?;

    parse_extraction_output(&raw)
}

/// Parse the raw string output from run_code into SurveyStructure.
/// Handles both camoufox (raw JSON) and Playwright (`### Result\n...`) formats.
fn parse_extraction_output(raw: &str) -> Result<SurveyStructure> {
    let text = raw.trim();

    // Playwright wraps result in "### Result"
    let text = if text.contains("### Result") {
        let re = Regex::new(r"### Result\s*\n(.*?)(?:\n###|\z)").unwrap();
        if let Some(cap) = re.captures(text) {
            cap[1].trim().to_string()
        } else {
            text.to_string()
        }
    } else {
        text.to_string()
    };

    // Strip outer quotes if present
    let text = if text.starts_with('"') && text.ends_with('"') {
        text[1..text.len() - 1].to_string()
    } else {
        text
    };

    // Try direct JSON parse
    if let Ok(v) = serde_json::from_str::<SurveyStructure>(&text) {
        return Ok(v);
    }

    // Try extracting JSON object from within text
    let re = Regex::new(r"\{.*\}").unwrap();
    if let Some(m) = re.find(&text) {
        if let Ok(v) = serde_json::from_str::<SurveyStructure>(m.as_str()) {
            return Ok(v);
        }
    }

    bail!("Failed to parse form structure: {}", &text[..text.len().min(500)])
}

// ── classify_subjects ─────────────────────────────────────────────────────────

/// Classify subjects into form fields vs quiz questions.
/// Mirrors Python `classify_subjects(subjects: list[dict]) -> dict`.
pub fn classify_subjects(subjects: &[Subject]) -> Classified {
    let mut company: Option<Subject> = None;
    let mut name: Option<Subject> = None;
    let mut email: Option<Subject> = None;
    let mut consent: Option<Subject> = None;
    let mut questions: Vec<Subject> = Vec::new();

    for s in subjects {
        let text_lower = s.text.to_lowercase();
        if text_lower.contains("公司") && s.subject_type == "radio" {
            company = Some(s.clone());
        } else if text_lower.contains("姓名") && s.subject_type == "text" {
            name = Some(s.clone());
        } else if text_lower.to_lowercase().contains("mail") && s.subject_type == "text" {
            email = Some(s.clone());
        } else if s.full_text.contains("同意") || s.full_text.contains("個資") {
            consent = Some(s.clone());
        } else if s.subject_type == "radio" && s.options.len() >= 2 {
            questions.push(s.clone());
        }
    }

    Classified {
        company,
        name,
        email,
        consent,
        questions,
    }
}

// ── save_survey ───────────────────────────────────────────────────────────────

/// Upsert survey + questions in SQLite. Returns the saved Survey row.
/// Mirrors Python `save_survey(db, url, survey_type, structure, classified) -> Survey`.
///
/// HANDOFF §7 quirk 8: upsert by url_hash — avoid duplicate surveys for same URL.
/// Python uses MD5; HANDOFF §3 says SHA-256. We use SHA-256 (stricter, matches HANDOFF).
pub async fn save_survey(
    pool: &SqlitePool,
    url: &str,
    survey_type: &str,
    structure: &SurveyStructure,
    classified: &Classified,
) -> Result<Survey> {
    let url_hash = md5_hex(url);
    let now = chrono::Utc::now();

    let company_options: Option<Value> = classified.company.as_ref().map(|c| {
        Value::Array(c.options.iter().map(|o| Value::String(o.clone())).collect())
    });
    let company_options_str = company_options
        .as_ref()
        .map(|v| v.to_string())
        .unwrap_or_default();
    let title = structure.title.as_deref().unwrap_or("");
    let raw_content = structure.body_text.as_deref().unwrap_or("");

    // Check for existing survey by url_hash
    let existing = sqlx::query_as!(
        SurveyRow,
        r#"SELECT
            id AS "id!",
            url AS "url!",
            url_hash AS "url_hash!",
            title,
            type AS "survey_type!",
            raw_content,
            company_options,
            created_at AS "created_at!"
        FROM surveys WHERE url_hash = ?"#,
        url_hash
    )
    .fetch_optional(pool)
    .await?;

    let survey_id = if let Some(ref row) = existing {
        // Update existing
        sqlx::query!(
            "UPDATE surveys SET title = ?, raw_content = ?, company_options = ? WHERE url_hash = ?",
            title,
            raw_content,
            company_options_str,
            url_hash
        )
        .execute(pool)
        .await?;

        // Preserve correct_answer + verified from old questions, then delete+re-insert
        let old_questions = sqlx::query!(
            "SELECT subject_id, correct_answer, verified FROM questions WHERE survey_id = ?",
            row.id
        )
        .fetch_all(pool)
        .await?;

        let preserved: std::collections::HashMap<String, (Option<String>, bool)> = old_questions
            .into_iter()
            .filter(|q| q.correct_answer.is_some())
            .map(|q| (q.subject_id, (q.correct_answer, q.verified != 0)))
            .collect();

        sqlx::query!("DELETE FROM questions WHERE survey_id = ?", row.id)
            .execute(pool)
            .await?;

        for q in &classified.questions {
            let qid = Uuid::new_v4().to_string();
            let (correct_answer, verified) = preserved
                .get(&q.id)
                .cloned()
                .unwrap_or((None, false));
            let options_json = serde_json::to_string(&q.options)?;
            let verified_int = verified as i64;
            sqlx::query!(
                "INSERT INTO questions (id, survey_id, subject_id, question_text, options, correct_answer, verified, created_at) \
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                qid,
                row.id,
                q.id,
                q.text,
                options_json,
                correct_answer,
                verified_int,
                now
            )
            .execute(pool)
            .await?;
        }

        row.id.clone()
    } else {
        // Insert new
        let new_id = Uuid::new_v4().to_string();
        sqlx::query!(
            "INSERT INTO surveys (id, url, url_hash, title, type, raw_content, company_options, created_at) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            new_id,
            url,
            url_hash,
            title,
            survey_type,
            raw_content,
            company_options_str,
            now
        )
        .execute(pool)
        .await?;

        for q in &classified.questions {
            let qid = Uuid::new_v4().to_string();
            let options_json = serde_json::to_string(&q.options)?;
            sqlx::query!(
                "INSERT INTO questions (id, survey_id, subject_id, question_text, options, correct_answer, verified, created_at) \
                 VALUES (?, ?, ?, ?, ?, NULL, 0, ?)",
                qid,
                new_id,
                q.id,
                q.text,
                options_json,
                now
            )
            .execute(pool)
            .await?;
        }

        new_id
    };

    // Fetch and return the saved survey
    let row = sqlx::query_as!(
        SurveyRow,
        r#"SELECT
            id AS "id!",
            url AS "url!",
            url_hash AS "url_hash!",
            title,
            type AS "survey_type!",
            raw_content,
            company_options,
            created_at AS "created_at!"
        FROM surveys WHERE id = ?"#,
        survey_id
    )
    .fetch_one(pool)
    .await?;

    row.into_survey()
}

// ── Internal helpers ──────────────────────────────────────────────────────────

/// MD5 hex digest — **must match Python `hashlib.md5(url.encode()).hexdigest()`**
/// for compatibility with existing PG `surveys.url_hash` values. DO NOT switch
/// to a stronger hash without also re-hashing all existing rows.
fn md5_hex(s: &str) -> String {
    let mut hasher = Md5::new();
    hasher.update(s.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Raw query result for surveys table (SQLite returns TEXT for most columns).
struct SurveyRow {
    id: String,
    url: String,
    url_hash: String,
    title: Option<String>,
    survey_type: String,
    raw_content: Option<String>,
    company_options: Option<String>,
    created_at: String,
}

impl SurveyRow {
    fn into_survey(self) -> Result<Survey> {
        let company_options = self
            .company_options
            .as_deref()
            .filter(|s| !s.is_empty())
            .and_then(|s| serde_json::from_str(s).ok());

        Ok(Survey {
            id: Uuid::parse_str(&self.id)
                .with_context(|| format!("invalid UUID in surveys.id: {}", self.id))?,
            url: self.url,
            url_hash: self.url_hash,
            title: self.title,
            survey_type: self.survey_type,
            raw_content: self.raw_content,
            company_options,
            created_at: self
                .created_at
                .parse()
                .with_context(|| format!("invalid timestamp: {}", self.created_at))?,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_md5_hex_length_matches_python() {
        // Python: hashlib.md5(b"https://www.surveycake.com/s/abc123").hexdigest()
        //   → "a62adb23a3d74c52ebf4bf86a56fc478" (32 chars)
        let h = md5_hex("https://www.surveycake.com/s/abc123");
        assert_eq!(h.len(), 32, "MD5 hex must be 32 chars");
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
        // Verified: hashlib.md5(b"https://www.surveycake.com/s/abc123").hexdigest()
        assert_eq!(h, "727fe9d964f309a51c315ae25c30d16a");
    }

    #[test]
    fn test_classify_subjects_company() {
        let subjects = vec![Subject {
            id: "subject-1".to_string(),
            num: 1,
            text: "公司名稱".to_string(),
            full_text: "公司名稱".to_string(),
            subject_type: "radio".to_string(),
            options: vec!["A公司".to_string(), "B公司".to_string()],
            has_input: false,
        }];
        let c = classify_subjects(&subjects);
        assert!(c.company.is_some());
        assert!(c.questions.is_empty());
    }

    #[test]
    fn test_classify_subjects_quiz_question() {
        let subjects = vec![Subject {
            id: "subject-5".to_string(),
            num: 5,
            text: "這題的正確答案是?".to_string(),
            full_text: "這題的正確答案是?".to_string(),
            subject_type: "radio".to_string(),
            options: vec!["A".to_string(), "B".to_string(), "C".to_string()],
            has_input: false,
        }];
        let c = classify_subjects(&subjects);
        assert!(c.company.is_none());
        assert_eq!(c.questions.len(), 1);
    }

    #[test]
    fn test_classify_subjects_name_email() {
        let subjects = vec![
            Subject {
                id: "subject-3".to_string(),
                num: 3,
                text: "姓名".to_string(),
                full_text: "姓名".to_string(),
                subject_type: "text".to_string(),
                options: vec![],
                has_input: true,
            },
            Subject {
                id: "subject-4".to_string(),
                num: 4,
                text: "Email".to_string(),
                full_text: "Email".to_string(),
                subject_type: "text".to_string(),
                options: vec![],
                has_input: true,
            },
        ];
        let c = classify_subjects(&subjects);
        assert!(c.name.is_some());
        assert!(c.email.is_some());
    }

    #[test]
    fn test_parse_extraction_output_direct_json() {
        let json = r#"{"title":"Test Survey","subjects":[],"bodyText":"hello"}"#;
        let s = parse_extraction_output(json).unwrap();
        assert_eq!(s.title.as_deref(), Some("Test Survey"));
    }

    #[test]
    fn test_parse_extraction_output_playwright_wrapped() {
        let wrapped = "### Result\n{\"title\":\"Test\",\"subjects\":[],\"bodyText\":\"\"}\n";
        let s = parse_extraction_output(wrapped).unwrap();
        assert_eq!(s.title.as_deref(), Some("Test"));
    }
}
