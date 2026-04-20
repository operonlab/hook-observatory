//! LiteLLM proxy + provider quota — port of Python `litellm_collector`.
//!
//! Live data sources (mirrors Python):
//!   - `GET /health/liveliness` (proxy alive check)
//!   - `GET /model/info`        (configured model list)
//!   - Redis `agent-metrics:provider:<name>:balance`  (provider balance overrides)
//!   - Redis `agent-metrics:dashscope:free_quota`     (Qwen free-tier metadata)
//!
//! Hardcoded defaults (`DEFAULT_QUOTAS`, `DASHSCOPE_DEFAULTS`) match the
//! Python module value-for-value so JSON parity is preserved.

use crate::config::Settings;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LitellmStatus {
    pub proxy_alive: bool,
    pub models_configured: Vec<String>,
    pub error: Option<String>,
}

pub async fn get_litellm_status(cfg: &Settings) -> LitellmStatus {
    let mut result = LitellmStatus {
        proxy_alive: false,
        models_configured: vec![],
        error: None,
    };

    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            result.error = Some(format!("client build failed: {e}"));
            return result;
        }
    };

    match client
        .get(format!("{}/health/liveliness", cfg.litellm_base_url))
        .send()
        .await
    {
        Ok(r) if r.status().is_success() => result.proxy_alive = true,
        Ok(_) => {}
        Err(e) => {
            result.error = Some(format!("Proxy unreachable: {e}"));
            return result;
        }
    }

    let resp = client
        .get(format!("{}/model/info", cfg.litellm_base_url))
        .header("Authorization", format!("Bearer {}", cfg.litellm_master_key))
        .timeout(Duration::from_secs(10))
        .send()
        .await;
    if let Ok(resp) = resp {
        if let Ok(body) = resp.json::<Value>().await {
            if let Some(arr) = body.get("data").and_then(|v| v.as_array()) {
                for m in arr {
                    let name = m
                        .get("model_name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("?")
                        .to_string();
                    result.models_configured.push(name);
                }
            }
        }
    }

    result
}

// ── Provider Quota Defaults ─────────────────────────────────────

#[derive(Debug, Clone)]
struct QuotaCell {
    total: f64,
    remaining: f64,
}

fn default_quotas() -> Vec<(&'static str, QuotaCell)> {
    vec![
        ("minimax",   QuotaCell { total: 25.0, remaining: 24.24 }),
        ("moonshot",  QuotaCell { total: 25.0, remaining: 23.67811 }),
        ("zhipu",     QuotaCell { total: 10.0, remaining: 10.0 }),
        ("deepseek",  QuotaCell { total: 12.0, remaining: 10.25 }),
        ("dashscope", QuotaCell { total: 0.0, remaining: 0.0 }),
        ("xai",       QuotaCell { total: 25.0, remaining: 25.0 }),
        ("google",    QuotaCell { total: 635.0, remaining: 549.35 }),
    ]
}

const PROVIDER_REDIS_PREFIX: &str = "agent-metrics:provider";
const DASHSCOPE_FREE_KEY: &str = "agent-metrics:dashscope:free_quota";

fn dashscope_defaults() -> Value {
    serde_json::json!({
        "total_models": 95,
        "healthy": 90,
        "over_50pct": 0,
        "over_80pct": 0,
        "no_free": 5,
        "top_models": [
            {"model": "qwen3-max",         "remaining": 999961, "total": 1000000},
            {"model": "qwen-max",          "remaining": 999984, "total": 1000000},
            {"model": "qwen3.5-122b-a10b", "remaining": 1000000, "total": 1000000}
        ]
    })
}

async fn open_redis(cfg: &Settings) -> Option<redis::aio::ConnectionManager> {
    let client = redis::Client::open(cfg.redis_url.clone()).ok()?;
    redis::aio::ConnectionManager::new(client).await.ok()
}

async fn provider_quotas(cfg: &Settings) -> Vec<(String, QuotaCell)> {
    let mut quotas: Vec<(String, QuotaCell)> = default_quotas()
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect();

    let mut conn = match open_redis(cfg).await {
        Some(c) => c,
        None => return quotas,
    };

    for (name, cell) in &mut quotas {
        if name == "dashscope" {
            continue;
        }
        let key = format!("{PROVIDER_REDIS_PREFIX}:{name}:balance");
        let raw: Option<String> = conn.get(&key).await.ok();
        if let Some(s) = raw {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                if let Some(t) = v.get("total").and_then(|x| x.as_f64()) {
                    cell.total = t;
                }
                if let Some(r) = v.get("remaining").and_then(|x| x.as_f64()) {
                    cell.remaining = r;
                }
            }
        }
    }
    quotas
}

pub async fn get_dashscope_free_quota(cfg: &Settings) -> Value {
    if let Some(mut conn) = open_redis(cfg).await {
        let raw: Option<String> = conn.get(DASHSCOPE_FREE_KEY).await.ok();
        if let Some(s) = raw {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                return v;
            }
        }
    }
    dashscope_defaults()
}

#[derive(Debug, Clone, Serialize)]
pub struct LitellmManualSummary {
    pub total_budget_usd: f64,
    pub total_remaining_usd: f64,
    pub total_spent_usd: f64,
    pub breakdown: Vec<Value>,
    pub dashscope_free_quota: Value,
}

pub async fn get_litellm_manual_summary(cfg: &Settings) -> LitellmManualSummary {
    let quotas = provider_quotas(cfg).await;
    let total_budget: f64 = quotas.iter().map(|(_, q)| q.total).sum();
    let total_remaining: f64 = quotas.iter().map(|(_, q)| q.remaining).sum();
    let total_spent = round4(total_budget - total_remaining);

    let dashscope_free = get_dashscope_free_quota(cfg).await;

    let mut breakdown = Vec::with_capacity(quotas.len());
    for (name, q) in &quotas {
        let spent = round4(q.total - q.remaining);
        let pct = if q.total > 0.0 {
            round1(spent / q.total * 100.0)
        } else {
            0.0
        };
        let mut entry = serde_json::json!({
            "name": name,
            "total": q.total,
            "remaining": q.remaining,
            "spent": spent,
            "pct": pct,
        });
        if name == "dashscope" {
            let total_models = dashscope_free.get("total_models").cloned().unwrap_or(Value::Null);
            entry["free_quota"] = dashscope_free.clone();
            entry["note"] = Value::String(format!(
                "免費額度 {} 模型，各 1M tokens",
                total_models
            ));
        } else if name == "google" {
            entry["note"] = Value::String("Google Cloud 抵免額".into());
        }
        breakdown.push(entry);
    }

    LitellmManualSummary {
        total_budget_usd: total_budget,
        total_remaining_usd: total_remaining,
        total_spent_usd: total_spent,
        breakdown,
        dashscope_free_quota: dashscope_free,
    }
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

fn round4(v: f64) -> f64 {
    (v * 10_000.0).round() / 10_000.0
}

