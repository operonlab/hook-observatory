//! Quota Redis-read shim.
//!
//! Phase 3 keeps `agent_metrics.quota_collector` (Python) running for now —
//! it owns the Anthropic/Codex/Gemini OAuth + Playwright fallback logic
//! (827 lines, scheduled for a separate Rust port phase).
//!
//! Here we just read the formatted snapshot Python writes to Redis under
//! `agent-metrics:quota:formatted`, plus the raw bundle under
//! `agent-metrics:quota:raw`. If Redis or the keys are missing, we return
//! "?" defaults so the sysmon snapshot still validates.

use crate::config::Settings;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value;

const RKEY_FORMATTED: &str = "agent-metrics:quota:formatted";
const RKEY_RAW: &str = "agent-metrics:quota:raw";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuotaFormatted {
    #[serde(default = "qmark")]
    pub llm_cc_5h: String,
    #[serde(default = "qmark")]
    pub llm_cc_7d: String,
    #[serde(default = "qmark")]
    pub llm_cc_ex: String,
    #[serde(default = "qmark")]
    pub llm_cx_5h: String,
    #[serde(default = "qmark")]
    pub llm_cx_7d: String,
    #[serde(default = "qmark")]
    pub llm_gm_pro: String,
    #[serde(default = "qmark")]
    pub llm_gm_flash: String,
    #[serde(default = "qmark")]
    pub llm_display: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_5h_resets_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_7d_resets_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cx_5h_resets_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cx_7d_resets_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_gm_daily_resets_at: Option<String>,
    // Claude Code Extra Usage (overage buffer) — absolute numbers for UI detail
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_ex_used_usd: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_ex_limit_usd: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_ex_balance_usd: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_ex_utilization: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm_cc_ex_enabled: Option<bool>,
}

impl Default for QuotaFormatted {
    fn default() -> Self {
        Self {
            llm_cc_5h: qmark(),
            llm_cc_7d: qmark(),
            llm_cc_ex: qmark(),
            llm_cx_5h: qmark(),
            llm_cx_7d: qmark(),
            llm_gm_pro: qmark(),
            llm_gm_flash: qmark(),
            llm_display: qmark(),
            llm_cc_5h_resets_at: None,
            llm_cc_7d_resets_at: None,
            llm_cx_5h_resets_at: None,
            llm_cx_7d_resets_at: None,
            llm_gm_daily_resets_at: None,
            llm_cc_ex_used_usd: None,
            llm_cc_ex_limit_usd: None,
            llm_cc_ex_balance_usd: None,
            llm_cc_ex_utilization: None,
            llm_cc_ex_enabled: None,
        }
    }
}

fn qmark() -> String {
    "?".into()
}

async fn open_redis(cfg: &Settings) -> Option<redis::aio::ConnectionManager> {
    let client = redis::Client::open(cfg.redis_url.clone()).ok()?;
    redis::aio::ConnectionManager::new(client).await.ok()
}

/// Read formatted quota from Redis. Falls back to all "?" defaults.
pub async fn get_quota(cfg: &Settings) -> QuotaFormatted {
    let mut conn = match open_redis(cfg).await {
        Some(c) => c,
        None => return QuotaFormatted::default(),
    };
    let raw: Option<String> = conn.get(RKEY_FORMATTED).await.ok();
    if let Some(s) = raw {
        serde_json::from_str(&s).unwrap_or_default()
    } else {
        QuotaFormatted::default()
    }
}

/// Read raw quota bundle (cc/cx/gm dicts). Used by /quota/current route.
pub async fn get_raw_cache(cfg: &Settings) -> Value {
    let mut conn = match open_redis(cfg).await {
        Some(c) => c,
        None => return Value::Null,
    };
    let raw: Option<String> = conn.get(RKEY_RAW).await.ok();
    raw.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_all_question_marks() {
        let q = QuotaFormatted::default();
        assert_eq!(q.llm_cc_5h, "?");
        assert_eq!(q.llm_display, "?");
    }

    #[test]
    fn missing_fields_default_to_qmark() {
        let v = serde_json::json!({
            "llm_cc_5h": "12k",
            "llm_display": "Claude 12k"
        });
        let parsed: QuotaFormatted = serde_json::from_value(v).unwrap();
        assert_eq!(parsed.llm_cc_5h, "12k");
        assert_eq!(parsed.llm_display, "Claude 12k");
        assert_eq!(parsed.llm_cc_7d, "?");
        assert_eq!(parsed.llm_gm_flash, "?");
    }
}
