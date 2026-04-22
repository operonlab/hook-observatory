//! Database models — mirror Python `models.py` ORM classes.
//! Phase 2 agent may extend this with SQL-specific wrappers.

use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct DailyRun {
    pub id: Uuid,
    pub run_date: NaiveDate,
    pub attend_url: Option<String>,
    pub quiz_url: Option<String>,
    pub status: String, // pending | running | completed | failed
    pub result_summary: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Survey {
    pub id: Uuid,
    pub url: String,
    pub url_hash: String,
    pub title: Option<String>,
    #[sqlx(rename = "type")]
    pub survey_type: String, // attendance | quiz
    pub raw_content: Option<String>,
    /// JSON array: `Vec<String>`
    pub company_options: Option<serde_json::Value>,
    pub created_at: DateTime<Utc>,
}

/// Question row.
///
/// `id` / `survey_id` are `String` (not `Uuid`) because sqlx's runtime
/// `FromRow` derive defaults to decoding `Uuid` as a 16-byte SQLite BLOB,
/// but the schema stores UUIDs as 36-char TEXT. The compile-time `query_as!`
/// macro sees the schema and picks the right decoder, but
/// `query_as::<_, Question>` (runtime) doesn't — so it failed at runtime
/// with "invalid length: expected 16 bytes, found 36". Keeping the id
/// fields on `String` is simpler than carrying a custom decoder
/// everywhere — callers that need a `Uuid` can `.parse()` on demand.
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Question {
    pub id: String,
    pub survey_id: String,
    pub subject_id: String,
    pub question_text: String,
    pub options: serde_json::Value, // JSON array
    pub correct_answer: Option<String>,
    pub verified: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Person {
    pub id: Uuid,
    pub name: String,
    pub email: String,
    pub company: String,
    pub active: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Submission {
    pub id: Uuid,
    pub survey_id: Uuid,
    pub person_id: Uuid,
    pub status: String, // success | failed | skipped
    pub score: Option<i32>,
    pub is_pathfinder: bool,
    pub answers_snapshot: Option<serde_json::Value>,
    pub error_message: Option<String>,
    pub submitted_at: DateTime<Utc>,
}
