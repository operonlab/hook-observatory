//! DashScope (Qwen) free quota sync — port of `ws_dashscope_quota_sync.py`.
//!
//! Cronicle invokes `agent-metrics-rs dashscope-quota-sync`. Scrapes the
//! Alibaba Cloud Model Studio free-quota dashboard via camoufox-cli, parses
//! the bilingual (CN/EN) UI, and writes Redis under
//! `agent-metrics:dashscope:free_quota` (7-day TTL).
//!
//! Parity choices vs Python:
//! - Camoufox is the only path; the Python script's Playwright/Safari
//!   fallbacks are skipped — the next 18:15 cron run will retry on its own
//!   if camoufox happens to fail. (Loss of error masking is acceptable
//!   for a 7-day-TTL data point that changes slowly.)

use anyhow::Result;
use chrono::Utc;
use fs2::FileExt;
use redis::AsyncCommands;
use regex::Regex;
use serde_json::{json, Value};
use std::fs::File;
use std::time::Duration;
use tokio::process::Command;

const REDIS_KEY: &str = "agent-metrics:dashscope:free_quota";
const REDIS_TTL_SECONDS: u64 = 86_400 * 7;
const CFX_SESSION: &str = "dashscope-sync";
const TARGET_URL: &str = "https://modelstudio.console.alibabacloud.com/ap-southeast-1/?tab=dashboard#/model-usage/free-quota";
const FALLBACK_JSON_PATH: &str = "/tmp/agent-metrics-qwen-quota.json";
const LOCK_FILE_PATH: &str = "/tmp/ws_dashscope_quota_sync.lock";

async fn cfx(args: &[&str], timeout_s: u64) -> Result<std::process::Output> {
    let mut cmd = Command::new("camoufox-cli");
    cmd.arg("--session").arg(CFX_SESSION);
    for a in args {
        cmd.arg(a);
    }
    let fut = cmd.kill_on_drop(true).output();
    Ok(tokio::time::timeout(Duration::from_secs(timeout_s), fut).await??)
}

async fn cfx_close() {
    let _ = cfx(&["close"], 10).await;
}

async fn scrape_with_camoufox() -> Option<String> {
    let opened = match cfx(&["--persistent", "open", TARGET_URL], 30).await {
        Ok(o) => o,
        Err(e) => {
            tracing::error!(error = %e, "cfx_open_failed");
            return None;
        }
    };
    if !opened.status.success() {
        tracing::error!(stderr = %String::from_utf8_lossy(&opened.stderr), "cfx_open_nonzero");
        cfx_close().await;
        return None;
    }
    tokio::time::sleep(Duration::from_secs(6)).await;
    let eval = cfx(
        &["eval", "document.body.innerText.substring(0, 8000)"],
        15,
    )
    .await;
    cfx_close().await;
    let out = eval.ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

/// Parse DashScope free-quota dashboard text (CN/EN bilingual).
///
/// Recognised "label-after-number" patterns (Python parity):
///   N\n模型總數                       → total_models
///   N\n額度充沛 / Sufficient quota    → healthy
///   N\n使用超50%                       → over_50pct
///   N\n使用超80%                       → over_80pct
///   N\n無免費額度 / no free quota      → no_free
///
/// Per-model entry, `top_models` list:
///   剩999,961/共1,000,000   (CN)
///   Remaining 999,961 / Total 1,000,000  (EN)
pub fn parse_free_quota(text: &str) -> Option<Value> {
    if text.len() < 50 {
        return None;
    }
    let lines: Vec<&str> = text.split('\n').collect();
    let mut total_models = 0_i64;
    let mut healthy = 0_i64;
    let mut over_50pct = 0_i64;
    let mut over_80pct = 0_i64;
    let mut no_free = 0_i64;
    let mut top_models: Vec<Value> = Vec::new();

    let re_cn = Regex::new(r"剩([\d,]+)/共([\d,]+)").unwrap();
    let re_en = Regex::new(r"Remaining\s*([\d,]+)\s*/\s*Total\s*([\d,]+)").unwrap();

    for (i, line) in lines.iter().enumerate() {
        let stripped = line.trim();
        if i + 1 < lines.len() {
            let next = lines[i + 1].trim();
            let n: Option<i64> = stripped.replace(',', "").parse().ok();
            if let Some(v) = n {
                if next.contains("模型总数")
                    || next.contains("模型總數")
                    || next.contains("Total Number of Models")
                {
                    total_models = v;
                } else if next.contains("额度充沛")
                    || next.contains("額度充沛")
                    || next.contains("Sufficient quota")
                {
                    healthy = v;
                } else if next.contains("使用超50%") || next.contains("over 50% used") {
                    over_50pct = v;
                } else if next.contains("使用超80%") || next.contains("over 80% used") {
                    over_80pct = v;
                } else if next.contains("无免费额度")
                    || next.contains("無免費額度")
                    || next.contains("no free quota")
                {
                    no_free = v;
                }
            }
        }

        let m = re_cn.captures(stripped).or_else(|| re_en.captures(stripped));
        if let Some(c) = m {
            if i == 0 {
                continue;
            }
            let remaining: i64 = c[1].replace(',', "").parse().unwrap_or(0);
            let total: i64 = c[2].replace(',', "").parse().unwrap_or(0);
            // Look back up to 3 lines for the model name (skip %-rows + quota rows)
            let mut model_name = String::new();
            for j in i.saturating_sub(3)..i {
                let cand = lines[j].trim();
                if !cand.is_empty()
                    && !cand.ends_with('%')
                    && !cand.contains('剩')
                    && !cand.contains("Remaining")
                {
                    model_name = cand.to_string();
                }
            }
            if !model_name.is_empty() {
                top_models.push(json!({
                    "model": model_name,
                    "remaining": remaining,
                    "total": total,
                }));
            }
        }
    }

    if total_models == 0 {
        return None;
    }
    Some(json!({
        "total_models": total_models,
        "healthy": healthy,
        "over_50pct": over_50pct,
        "over_80pct": over_80pct,
        "no_free": no_free,
        "top_models": top_models,
        "synced_at": Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false),
    }))
}

async fn store_to_redis(redis_url: &str, data: &Value) -> bool {
    let client = match redis::Client::open(redis_url.to_string()) {
        Ok(c) => c,
        Err(_) => return false,
    };
    let mut conn = match redis::aio::ConnectionManager::new(client).await {
        Ok(c) => c,
        Err(_) => return false,
    };
    conn.set_ex::<_, _, ()>(REDIS_KEY, data.to_string(), REDIS_TTL_SECONDS)
        .await
        .is_ok()
}

pub async fn run_once(redis_url: &str) -> Result<bool> {
    let lock_file = File::create(LOCK_FILE_PATH)?;
    if lock_file.try_lock_exclusive().is_err() {
        tracing::info!(path = LOCK_FILE_PATH, "another sync already running — skip");
        return Ok(false);
    }

    tracing::info!("=== Qwen Free Quota Sync Start ===");
    let text = match scrape_with_camoufox().await {
        Some(t) => t,
        None => {
            tracing::error!("camoufox scrape failed");
            let _ = lock_file.unlock();
            return Ok(false);
        }
    };
    tracing::info!(chars = text.len(), "scraped");

    let data = match parse_free_quota(&text) {
        Some(d) => d,
        None => {
            tracing::error!(
                preview = %text.chars().take(300).collect::<String>(),
                "parse failed"
            );
            let _ = lock_file.unlock();
            return Ok(false);
        }
    };
    tracing::info!(
        total_models = data["total_models"].as_i64().unwrap_or(0),
        healthy = data["healthy"].as_i64().unwrap_or(0),
        top = data["top_models"].as_array().map(|a| a.len()).unwrap_or(0),
        "parsed"
    );

    let stored = store_to_redis(redis_url, &data).await;
    if !stored {
        let _ = std::fs::write(
            FALLBACK_JSON_PATH,
            serde_json::to_string_pretty(&data).unwrap_or_default(),
        );
        tracing::warn!(path = FALLBACK_JSON_PATH, "redis failed; wrote fallback JSON");
    } else {
        tracing::info!(key = REDIS_KEY, ttl_s = REDIS_TTL_SECONDS, "stored");
    }
    tracing::info!("=== Qwen Free Quota Sync Done ===");
    let _ = lock_file.unlock();
    Ok(stored)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_traditional_chinese_layout() {
        let text = "\
95\n模型總數\n\
90\n額度充沛\n\
0\n使用超50%\n\
0\n使用超80%\n\
5\n無免費額度\n\
qwen3-max\n0%\n剩999,961/共1,000,000\n\
qwen-max\n0%\n剩999,984/共1,000,000\n\
";
        let v = parse_free_quota(text).expect("parsed");
        assert_eq!(v["total_models"], 95);
        assert_eq!(v["healthy"], 90);
        assert_eq!(v["no_free"], 5);
        let tm = v["top_models"].as_array().unwrap();
        assert_eq!(tm.len(), 2);
        assert_eq!(tm[0]["model"].as_str().unwrap(), "qwen3-max");
        assert_eq!(tm[0]["remaining"], 999_961);
        assert_eq!(tm[0]["total"], 1_000_000);
    }

    #[test]
    fn parse_english_layout() {
        let text = "\
95\nTotal Number of Models\n\
90\nSufficient quota\n\
qwen3-max\nRemaining 999,961 / Total 1,000,000\n\
";
        let v = parse_free_quota(text).expect("parsed");
        assert_eq!(v["total_models"], 95);
        assert_eq!(v["healthy"], 90);
        let tm = v["top_models"].as_array().unwrap();
        assert_eq!(tm.len(), 1);
        assert_eq!(tm[0]["model"].as_str().unwrap(), "qwen3-max");
        assert_eq!(tm[0]["remaining"], 999_961);
    }

    #[test]
    fn rejects_short_text() {
        assert!(parse_free_quota("").is_none());
        assert!(parse_free_quota("too short").is_none());
    }

    #[test]
    fn rejects_when_no_total_models() {
        let text = "\
foo\nbar\n\
qwen-max\n剩100/共1000\n\
"
        .repeat(5);
        assert!(parse_free_quota(&text).is_none());
    }
}
