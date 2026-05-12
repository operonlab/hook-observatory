//! Usage collector — port of Python `usage_collector`.
//!
//! Wraps `ccusage` binary for Claude Code usage data, normalizes the JSON
//! to the legacy `ccusage` format, then merges with LiteLLM provider summary.
//! Redis key strategy is identical (TTL 600s) so the cache is interoperable
//! with the Python version during cutover.

use crate::collectors::litellm::{get_litellm_manual_summary, LitellmManualSummary};
use crate::config::Settings;
use anyhow::Result;
use chrono::{Datelike, Duration as ChronoDuration, Utc};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;
use tokio::process::Command;

const CACHE_KEY_MTD: &str = "agent-metrics:usage:mtd";
const CACHE_KEY_MODELS: &str = "agent-metrics:usage:models";
const CACHE_KEY_RAW: &str = "agent-metrics:usage:raw";
const CACHE_KEY_DAILY: &str = "agent-metrics:usage:daily-cost";
const CACHE_TTL: usize = 600;
const CCUSAGE_BIN: &str = "/Users/joneshong/.local/bin/ccusage";

async fn open_redis(cfg: &Settings) -> Option<redis::aio::ConnectionManager> {
    let client = redis::Client::open(cfg.redis_url.clone()).ok()?;
    redis::aio::ConnectionManager::new(client).await.ok()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CcusageTotals {
    #[serde(rename = "totalCost")]
    pub total_cost: f64,
    #[serde(rename = "totalTokens")]
    pub total_tokens: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CcusageDay {
    pub date: String,
    #[serde(rename = "totalCost")]
    pub total_cost: f64,
    #[serde(rename = "modelBreakdowns")]
    pub model_breakdowns: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CcusageData {
    pub daily: Vec<CcusageDay>,
    pub totals: CcusageTotals,
}

/// Translate ccusage nested JSON into legacy ccusage format.
/// Mirrors `_normalize_rs_json` in Python.
fn normalize_rs_json(data: &Value) -> CcusageData {
    let mut total_cost = 0.0;
    let mut total_tokens: i64 = 0;
    let mut daily = Vec::new();

    let token_keys = [
        "input_tokens",
        "output_tokens",
        "cache_creation_5m_tokens",
        "cache_creation_1h_tokens",
        "cache_read_tokens",
        "thinking_tokens",
    ];

    if let Some(days) = data.get("Daily").and_then(|v| v.as_array()) {
        for d in days {
            let tc = d.get("total_cost").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let mut tokens_sum: i64 = 0;
            if let Some(tokens) = d.get("total_tokens") {
                for k in &token_keys {
                    tokens_sum += tokens.get(k).and_then(|v| v.as_i64()).unwrap_or(0);
                }
            }
            let mut breakdowns = Vec::new();
            if let Some(by_model) = d.get("by_model").and_then(|v| v.as_object()) {
                for (name, mu) in by_model {
                    let cost: f64 = mu
                        .get("cost")
                        .and_then(|v| v.as_object())
                        .map(|o| o.values().filter_map(|x| x.as_f64()).sum())
                        .unwrap_or(0.0);
                    breakdowns.push(json!({
                        "modelName": name,
                        "cost": cost,
                    }));
                }
            }
            daily.push(CcusageDay {
                date: d.get("date").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                total_cost: tc,
                model_breakdowns: breakdowns,
            });
            total_cost += tc;
            total_tokens += tokens_sum;
        }
    }

    CcusageData {
        daily,
        totals: CcusageTotals {
            total_cost,
            total_tokens,
        },
    }
}

async fn ccusage_raw(cfg: &Settings, since: &str) -> CcusageData {
    let cache_key = format!("{CACHE_KEY_RAW}:{since}");
    if let Some(mut conn) = open_redis(cfg).await {
        let cached: Option<String> = conn.get(&cache_key).await.ok();
        if let Some(s) = cached {
            if let Ok(d) = serde_json::from_str::<CcusageData>(&s) {
                return d;
            }
        }
    }

    let out = Command::new(CCUSAGE_BIN)
        .args(["daily", "--since", since, "--json"])
        .kill_on_drop(true)
        .output();

    let out = match tokio::time::timeout(Duration::from_secs(45), out).await {
        Ok(Ok(o)) => o,
        _ => return CcusageData::default(),
    };
    if !out.status.success() {
        return CcusageData::default();
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    let parsed: Value = match serde_json::from_str(&stdout) {
        Ok(v) => v,
        Err(_) => return CcusageData::default(),
    };

    let data = if parsed.get("Daily").is_some() {
        normalize_rs_json(&parsed)
    } else {
        serde_json::from_value(parsed).unwrap_or_default()
    };

    if let Some(mut conn) = open_redis(cfg).await {
        if let Ok(s) = serde_json::to_string(&data) {
            let _: Result<(), _> = conn.set_ex::<_, _, ()>(&cache_key, s, CACHE_TTL as u64).await;
        }
    }

    data
}

#[derive(Debug, Clone, Serialize)]
pub struct ClaudeBudget {
    pub used_usd: f64,
    pub budget_usd: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct LitellmBudget {
    pub used_usd: f64,
    pub budget_usd: f64,
    pub remaining_usd: f64,
    pub breakdown: Vec<Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct MonthToDate {
    pub claude: ClaudeBudget,
    pub litellm: LitellmBudget,
}

pub async fn get_month_to_date(cfg: &Settings) -> MonthToDate {
    if let Some(mut conn) = open_redis(cfg).await {
        let cached: Option<String> = conn.get(CACHE_KEY_MTD).await.ok();
        if let Some(s) = cached {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                return mtd_from_value(v);
            }
        }
    }

    let now = Utc::now();
    let month_start = now.date_naive().with_day(1).unwrap();
    let since = month_start.format("%Y%m%d").to_string();
    let raw = ccusage_raw(cfg, &since).await;
    let cc_cost = raw.totals.total_cost;

    let lt: LitellmManualSummary = get_litellm_manual_summary(cfg).await;
    let result = MonthToDate {
        claude: ClaudeBudget {
            used_usd: round2(cc_cost),
            budget_usd: 5000.0,
        },
        litellm: LitellmBudget {
            used_usd: lt.total_spent_usd,
            budget_usd: lt.total_budget_usd,
            remaining_usd: lt.total_remaining_usd,
            breakdown: lt.breakdown,
        },
    };

    if let Some(mut conn) = open_redis(cfg).await {
        if let Ok(s) = serde_json::to_string(&result) {
            let _: Result<(), _> =
                conn.set_ex::<_, _, ()>(CACHE_KEY_MTD, s, CACHE_TTL as u64).await;
        }
    }
    result
}

fn mtd_from_value(v: Value) -> MonthToDate {
    let claude = v
        .get("claude")
        .map(|c| ClaudeBudget {
            used_usd: c.get("used_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
            budget_usd: c.get("budget_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
        })
        .unwrap_or(ClaudeBudget {
            used_usd: 0.0,
            budget_usd: 0.0,
        });
    let litellm = v
        .get("litellm")
        .map(|l| LitellmBudget {
            used_usd: l.get("used_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
            budget_usd: l.get("budget_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
            remaining_usd: l.get("remaining_usd").and_then(|x| x.as_f64()).unwrap_or(0.0),
            breakdown: l
                .get("breakdown")
                .and_then(|x| x.as_array().cloned())
                .unwrap_or_default(),
        })
        .unwrap_or(LitellmBudget {
            used_usd: 0.0,
            budget_usd: 0.0,
            remaining_usd: 0.0,
            breakdown: vec![],
        });
    MonthToDate { claude, litellm }
}

#[derive(Debug, Clone, Serialize)]
pub struct ClaudeModelEntry {
    pub model: String,
    pub cost_usd: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModelBreakdown {
    pub claude_models: Vec<ClaudeModelEntry>,
    pub litellm_models: Vec<Value>,
}

pub async fn get_model_breakdown(cfg: &Settings, days: i64) -> ModelBreakdown {
    let cache_key = format!("{CACHE_KEY_MODELS}:{days}");
    if let Some(mut conn) = open_redis(cfg).await {
        let cached: Option<String> = conn.get(&cache_key).await.ok();
        if let Some(s) = cached {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                return ModelBreakdown {
                    claude_models: v
                        .get("claude_models")
                        .and_then(|x| x.as_array())
                        .map(|arr| {
                            arr.iter()
                                .map(|e| ClaudeModelEntry {
                                    model: e
                                        .get("model")
                                        .and_then(|x| x.as_str())
                                        .unwrap_or("?")
                                        .into(),
                                    cost_usd: e
                                        .get("cost_usd")
                                        .and_then(|x| x.as_f64())
                                        .unwrap_or(0.0),
                                })
                                .collect()
                        })
                        .unwrap_or_default(),
                    litellm_models: v
                        .get("litellm_models")
                        .and_then(|x| x.as_array().cloned())
                        .unwrap_or_default(),
                };
            }
        }
    }

    let since = (Utc::now() - ChronoDuration::days(days))
        .format("%Y%m%d")
        .to_string();
    let raw = ccusage_raw(cfg, &since).await;
    use std::collections::BTreeMap;
    let mut cc: BTreeMap<String, f64> = BTreeMap::new();
    for day in &raw.daily {
        for mb in &day.model_breakdowns {
            let name = mb
                .get("modelName")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();
            let cost = mb.get("cost").and_then(|v| v.as_f64()).unwrap_or(0.0);
            *cc.entry(name).or_insert(0.0) += cost;
        }
    }
    let mut claude_models: Vec<ClaudeModelEntry> = cc
        .into_iter()
        .map(|(model, cost)| ClaudeModelEntry { model, cost_usd: cost })
        .collect();
    claude_models.sort_by(|a, b| {
        b.cost_usd
            .partial_cmp(&a.cost_usd)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let lt = get_litellm_manual_summary(cfg).await;
    let mut litellm_models = lt.breakdown.clone();
    litellm_models.sort_by(|a, b| {
        let av = a.get("spent").and_then(|x| x.as_f64()).unwrap_or(0.0);
        let bv = b.get("spent").and_then(|x| x.as_f64()).unwrap_or(0.0);
        bv.partial_cmp(&av).unwrap_or(std::cmp::Ordering::Equal)
    });

    let result = ModelBreakdown {
        claude_models,
        litellm_models,
    };

    if let Some(mut conn) = open_redis(cfg).await {
        if let Ok(s) = serde_json::to_string(&result) {
            let _: Result<(), _> = conn.set_ex::<_, _, ()>(&cache_key, s, CACHE_TTL as u64).await;
        }
    }
    result
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TodayCost {
    pub date: String,
    pub cost: f64,
    pub updated: String,
}

pub async fn get_today_cost(cfg: &Settings) -> TodayCost {
    if let Some(mut conn) = open_redis(cfg).await {
        let cached: Option<String> = conn.get(CACHE_KEY_DAILY).await.ok();
        if let Some(s) = cached {
            if let Ok(v) = serde_json::from_str::<TodayCost>(&s) {
                return v;
            }
        }
    }

    let now = Utc::now();
    let today_dash = now.format("%Y-%m-%d").to_string();
    let month_start = now.date_naive().with_day(1).unwrap().format("%Y%m%d").to_string();
    let raw = ccusage_raw(cfg, &month_start).await;
    let cost = raw
        .daily
        .iter()
        .find(|d| d.date == today_dash)
        .map(|d| d.total_cost)
        .unwrap_or(0.0);

    let result = TodayCost {
        date: today_dash,
        cost: round2(cost),
        updated: now.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false),
    };
    if let Some(mut conn) = open_redis(cfg).await {
        if let Ok(s) = serde_json::to_string(&result) {
            let _: Result<(), _> =
                conn.set_ex::<_, _, ()>(CACHE_KEY_DAILY, s, CACHE_TTL as u64).await;
        }
    }
    result
}

fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}
