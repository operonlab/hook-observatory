//! Provider balance sync — port of `schedules/runners/ws_provider_balance_sync.py`.
//!
//! Cronicle invokes `agent-metrics provider-balance-sync` (every few hours).
//! Internally:
//!   1. Use camoufox-cli (Python wrapper, persistent Firefox profile w/ user cookies)
//!      to open each provider's billing/balance page and eval the body innerText.
//!   2. Parse 6 different layouts via regex (matches Python parsers byte-for-byte).
//!   3. Write each result to Redis under `agent-metrics:provider:{name}:balance`
//!      with 7-day TTL + a combined `:all_balances` summary.
//!   4. flock guard against concurrent runs (mirrors Python's `fcntl.flock`).

use anyhow::Result;
use chrono::Utc;
use fs2::FileExt;
use redis::AsyncCommands;
use regex::Regex;
use serde::Serialize;
use serde_json::{json, Value};
use std::fs::File;
use std::path::Path;
use std::time::Duration;
use tokio::process::Command;

const REDIS_KEY_PREFIX: &str = "agent-metrics:provider";
const REDIS_TTL_SECONDS: u64 = 86_400 * 7;
const CFX_SESSION: &str = "balance-sync";
const FALLBACK_JSON_PATH: &str = "/tmp/agent-metrics-provider-balances.json";
const LOCK_FILE_PATH: &str = "/tmp/ws_provider_balance_sync.lock";

#[derive(Debug, Clone)]
struct ProviderCfg {
    name: &'static str,
    url: &'static str,
    total: f64,
}

const PROVIDERS: &[ProviderCfg] = &[
    ProviderCfg { name: "minimax",   url: "https://platform.minimax.io/user-center/payment/balance", total: 25.0 },
    ProviderCfg { name: "moonshot",  url: "https://platform.moonshot.ai/console/account",            total: 25.0 },
    ProviderCfg { name: "zhipu",     url: "https://z.ai/manage-apikey/billing",                      total: 10.0 },
    ProviderCfg { name: "deepseek",  url: "https://platform.deepseek.com/usage",                     total: 12.0 },
    ProviderCfg { name: "xai",       url: "https://console.x.ai/team/f0ca6117-e73f-4fec-b5ab-4391eb612200/billing", total: 25.0 },
    ProviderCfg { name: "google",    url: "https://console.cloud.google.com/billing/credits?hl=zh-tw", total: 635.0 },
];

#[derive(Debug, Clone, Serialize)]
pub struct ProviderResult {
    pub name: String,
    pub total: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub remaining: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub spent: Option<f64>,
    pub source: &'static str,
    pub synced_at: String,
    pub status: &'static str,
}

// ── camoufox-cli helpers ────────────────────────────────────────

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

/// Open each provider URL sequentially, return innerText body for each.
async fn scrape_all_providers() -> std::collections::BTreeMap<String, String> {
    let mut out: std::collections::BTreeMap<String, String> = Default::default();
    if PROVIDERS.is_empty() {
        return out;
    }

    // Open the first URL with --persistent so the persistent Firefox profile is loaded.
    let first = &PROVIDERS[0];
    let open_r = match cfx(&["--persistent", "open", first.url], 30).await {
        Ok(o) => o,
        Err(e) => {
            tracing::error!(error = %e, "cfx_open_initial_failed");
            return out;
        }
    };
    if !open_r.status.success() {
        tracing::error!(
            stderr = %String::from_utf8_lossy(&open_r.stderr),
            "cfx_open_initial_nonzero"
        );
        cfx_close().await;
        return out;
    }
    tokio::time::sleep(Duration::from_secs(6)).await;

    // First eval
    let eval = cfx(
        &["eval", "document.body.innerText.substring(0, 5000)"],
        15,
    )
    .await;
    let text = eval
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
        .unwrap_or_default();
    tracing::info!(provider = first.name, chars = text.len(), "scraped");
    out.insert(first.name.into(), text);

    // Remaining providers
    for p in &PROVIDERS[1..] {
        if let Err(e) = cfx(&["open", p.url], 20).await {
            tracing::warn!(provider = p.name, error = %e, "cfx_open_failed");
            continue;
        }
        tokio::time::sleep(Duration::from_secs(6)).await;
        let eval = cfx(
            &["eval", "document.body.innerText.substring(0, 5000)"],
            15,
        )
        .await;
        let text = eval
            .ok()
            .filter(|o| o.status.success())
            .map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
            .unwrap_or_default();
        tracing::info!(provider = p.name, chars = text.len(), "scraped");
        out.insert(p.name.into(), text);
    }

    cfx_close().await;
    out
}

// ── Parsers (regex translated 1:1 from Python) ─────────────────

fn rx(p: &str) -> Regex {
    Regex::new(p).expect("regex valid")
}

fn first_capture_f64(re: &Regex, text: &str) -> Option<f64> {
    re.captures(text)
        .and_then(|c| c.get(1))
        .and_then(|m| m.as_str().replace(',', "").parse::<f64>().ok())
}

pub fn parse_minimax(text: &str) -> Option<f64> {
    if text.is_empty() || text.contains("Sign in") {
        return None;
    }
    if let Some(v) = first_capture_f64(&rx(r"\$\s*([\d,]+\.?\d+)\s*\n\s*Current balance"), text) {
        return Some(v);
    }
    if let Some(v) = first_capture_f64(&rx(r"Current balance\s*\n\s*([\d,]+\.?\d+)"), text) {
        return Some(v);
    }
    if let Some(v) = first_capture_f64(&rx(r"\$\s*([\d,]+\.?\d+)"), text) {
        if v > 0.0 && v < 10_000.0 {
            return Some(v);
        }
    }
    None
}

pub fn parse_moonshot(text: &str) -> Option<f64> {
    if text.is_empty() || text.contains("Sign in") {
        return None;
    }
    if let Some(v) = first_capture_f64(&rx(r"Balance\s*\(\$\)\s*\n?\s*([\d,]+\.?\d+)"), text) {
        return Some(v);
    }
    if let Some(v) = first_capture_f64(&rx(r"[Bb]alance[:\s]*\$?\s*([\d,]+\.?\d+)"), text) {
        if v > 0.0 && v < 10_000.0 {
            return Some(v);
        }
    }
    None
}

pub fn parse_zhipu(text: &str) -> Option<f64> {
    if text.is_empty() || text.contains("Sign in") {
        return None;
    }
    if let Some(v) = first_capture_f64(&rx(r"\$\s*([\d,]+\.?\d+)\s*\n\s*Cash balance"), text) {
        return Some(v);
    }
    if let Some(v) = first_capture_f64(&rx(r"Cash balance\s*\n?\s*\$?\s*([\d,]+\.?\d+)"), text) {
        return Some(v);
    }
    if let Some(v) = first_capture_f64(&rx(r"\$\s*([\d,]+\.?\d+)"), text) {
        if v > 0.0 && v < 10_000.0 {
            return Some(v);
        }
    }
    None
}

pub fn parse_deepseek(text: &str) -> Option<f64> {
    if text.is_empty() || text.contains("Sign in") || text.contains("登录") {
        return None;
    }
    // Note: Python uses 「充值[余餘][额額]」 — both Simplified and Traditional accepted.
    if let Some(v) = first_capture_f64(
        &rx(r"充值[余餘][额額]\s*\n?\s*\$\s*([\d,]+\.?\d+)"),
        text,
    ) {
        return Some(v);
    }
    if let Some(v) = first_capture_f64(&rx(r"[Bb]alance\s*\n?\s*\$\s*([\d,]+\.?\d+)"), text) {
        return Some(v);
    }
    None
}

pub fn parse_xai(text: &str) -> Option<f64> {
    if text.is_empty() || text.contains("Access to team denied") {
        return None;
    }
    // 2026-04 layout: "Credits\n... credit balance ...\n$X"
    let re_new = Regex::new(
        r"(?i)Credits\s*\n\s*[^\n]*credit balance[^\n]*\n\s*\$\s*([\d,]+\.?\d+)",
    )
    .unwrap();
    if let Some(v) = first_capture_f64(&re_new, text) {
        return Some(v);
    }
    // Legacy: Purchased + Free - API spend
    let re_purchased = Regex::new(r"(?s)Purchased credits[^$]*\$\s*([\d,]+\.?\d+)").unwrap();
    let re_free = Regex::new(r"(?s)Free credits[^$]*\$\s*([\d,]+\.?\d+)").unwrap();
    let re_spend = Regex::new(r"API spend\s*\n\s*\$\s*([\d,]+\.?\d+)").unwrap();
    let purchased = first_capture_f64(&re_purchased, text)?;
    let free = first_capture_f64(&re_free, text).unwrap_or(0.0);
    let spend = first_capture_f64(&re_spend, text).unwrap_or(0.0);
    Some(round4(purchased + free - spend))
}

/// Google Cloud billing credits: sum only `可使用` rows, skip `已過期`.
pub fn parse_google(text: &str) -> Option<(f64, f64)> {
    if text.is_empty() || text.contains("Sign in") {
        return None;
    }
    let re_dollar = Regex::new(r"\$\s*([\d,]+\.?\d+)").unwrap();
    let lines: Vec<&str> = text.split('\n').collect();
    let mut total_remaining = 0.0_f64;
    let mut total_original = 0.0_f64;
    let mut found = false;
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i].trim();
        if line.contains("可使用") {
            // Find next two dollar amounts within 7 lines
            let mut remaining_val: Option<f64> = None;
            let mut original_val: Option<f64> = None;
            let upper = (i + 8).min(lines.len());
            let mut j = i + 1;
            while j < upper {
                if let Some(c) = re_dollar.captures(lines[j]) {
                    if let Ok(v) = c[1].replace(',', "").parse::<f64>() {
                        if remaining_val.is_none() {
                            remaining_val = Some(v);
                        } else if original_val.is_none() {
                            original_val = Some(v);
                            break;
                        }
                    }
                }
                j += 1;
            }
            if let Some(r) = remaining_val {
                total_remaining += r;
                total_original += original_val.unwrap_or(r);
                found = true;
            }
        }
        // 已過期: skip (no-op)
        i += 1;
    }
    if found {
        Some((round2(total_remaining), round2(total_original)))
    } else {
        None
    }
}

fn round4(v: f64) -> f64 {
    (v * 10_000.0).round() / 10_000.0
}
fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}

// ── Redis writer ────────────────────────────────────────────────

async fn store_results(
    redis_url: &str,
    results: &std::collections::BTreeMap<String, Value>,
) -> usize {
    let client = match redis::Client::open(redis_url.to_string()) {
        Ok(c) => c,
        Err(e) => {
            tracing::error!(error = %e, "redis_client_open_failed");
            return 0;
        }
    };
    let mut conn = match redis::aio::ConnectionManager::new(client).await {
        Ok(c) => c,
        Err(e) => {
            tracing::error!(error = %e, "redis_connect_failed");
            return 0;
        }
    };
    let mut ok = 0usize;
    for (name, data) in results {
        if data.get("status").and_then(|v| v.as_str()) == Some("ok") {
            let key = format!("{REDIS_KEY_PREFIX}:{name}:balance");
            let _: Result<(), _> = conn
                .set_ex::<_, _, ()>(key, data.to_string(), REDIS_TTL_SECONDS)
                .await;
            ok += 1;
        }
    }
    let summary = serde_json::Value::Object(
        results
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
    );
    let _: Result<(), _> = conn
        .set_ex::<_, _, ()>(
            format!("{REDIS_KEY_PREFIX}:all_balances"),
            summary.to_string(),
            REDIS_TTL_SECONDS,
        )
        .await;
    ok
}

// ── Public entry ────────────────────────────────────────────────

/// Run a single sync pass. Acquires a non-blocking flock on
/// `/tmp/ws_provider_balance_sync.lock`; if another instance holds the lock,
/// returns immediately with `Ok(0)`.
pub async fn run_once(redis_url: &str) -> Result<usize> {
    // flock guard (mirror Python's fcntl.LOCK_EX|LOCK_NB)
    let lock_file = File::create(LOCK_FILE_PATH)?;
    if lock_file.try_lock_exclusive().is_err() {
        tracing::info!(path = LOCK_FILE_PATH, "another sync already running — skip");
        return Ok(0);
    }

    tracing::info!("=== Provider Balance Sync Start (camoufox) ===");

    let raw_texts = scrape_all_providers().await;
    if raw_texts.is_empty() {
        tracing::error!("no data scraped from any provider");
        let _ = lock_file.unlock();
        return Ok(0);
    }

    let ts = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let mut results: std::collections::BTreeMap<String, Value> = Default::default();

    for cfg in PROVIDERS {
        let text = raw_texts.get(cfg.name).cloned().unwrap_or_default();
        if text.is_empty() {
            results.insert(
                cfg.name.into(),
                json!({
                    "status": "scrape_failed",
                    "total": cfg.total,
                    "synced_at": ts,
                }),
            );
            continue;
        }

        let parsed: Option<(f64, f64)> = match cfg.name {
            "minimax" => parse_minimax(&text).map(|r| (r, cfg.total)),
            "moonshot" => parse_moonshot(&text).map(|r| (r, cfg.total)),
            "zhipu" => parse_zhipu(&text).map(|r| (r, cfg.total)),
            "deepseek" => parse_deepseek(&text).map(|r| (r, cfg.total)),
            "xai" => parse_xai(&text).map(|r| (r, cfg.total)),
            "google" => parse_google(&text),
            _ => None,
        };

        if let Some((remaining, original)) = parsed {
            let total = if cfg.name == "google" { original } else { cfg.total };
            results.insert(
                cfg.name.into(),
                json!({
                    "name": cfg.name,
                    "total": total,
                    "remaining": remaining,
                    "spent": round4(total - remaining),
                    "source": "scraped",
                    "synced_at": ts,
                    "status": "ok",
                }),
            );
            tracing::info!(provider = cfg.name, remaining, "ok");
        } else {
            results.insert(
                cfg.name.into(),
                json!({
                    "status": "parse_failed",
                    "total": cfg.total,
                    "synced_at": ts,
                }),
            );
            tracing::warn!(provider = cfg.name, "parse_failed");
        }
    }

    let ok = store_results(redis_url, &results).await;
    tracing::info!(stored = ok, total = results.len(), "Stored to Redis");

    // Fallback JSON for offline debugging
    if let Ok(blob) = serde_json::to_string_pretty(&results) {
        let _ = std::fs::write(FALLBACK_JSON_PATH, blob);
    }

    tracing::info!("=== Provider Balance Sync Done: {ok}/{} OK ===", results.len());
    let _ = lock_file.unlock();
    Ok(ok)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn minimax_parses_dollar_then_balance() {
        let text = "$24.24\nCurrent balance\nlast updated";
        assert_eq!(parse_minimax(text), Some(24.24));
    }

    #[test]
    fn minimax_rejects_signin_page() {
        assert_eq!(parse_minimax("Sign in to your account"), None);
    }

    #[test]
    fn moonshot_parses_balance_dollar_label() {
        let text = "Balance ($)\n23.67811";
        assert_eq!(parse_moonshot(text), Some(23.67811));
    }

    #[test]
    fn zhipu_parses_dollar_then_cash_balance() {
        let text = "$ 10.00\nCash balance\nfooter";
        assert_eq!(parse_zhipu(text), Some(10.00));
    }

    #[test]
    fn deepseek_parses_simplified_chinese_label() {
        let text = "充值余额\n$10.25\nUSD";
        assert_eq!(parse_deepseek(text), Some(10.25));
    }

    #[test]
    fn deepseek_parses_traditional_chinese_label() {
        let text = "充值餘額\n$5.50\nUSD";
        assert_eq!(parse_deepseek(text), Some(5.50));
    }

    #[test]
    fn xai_new_layout_credits_section() {
        let text = "Credits\nYour credit balance for API usage\n$24.82\nPurchase credits";
        assert_eq!(parse_xai(text), Some(24.82));
    }

    #[test]
    fn xai_legacy_layout_purchased_minus_spend() {
        let text = "Purchased credits\nfoo\n$50.00\nFree credits\nbar\n$10.00\nAPI spend\n$5.00\n";
        assert_eq!(parse_xai(text), Some(55.00));
    }

    #[test]
    fn google_sums_only_active_credits() {
        // Two credits: one 可使用 ($100 / $200 original), one 已過期 ($50 / $300 original)
        let text = "\
Credit Alpha\n 可使用\t\n50%\n$100.00\n\t$200.00\t\n\
Credit Beta\n 已過期\t\n—\n$50.00\n\t$300.00\t\n";
        assert_eq!(parse_google(text), Some((100.00, 200.00)));
    }

    #[test]
    fn google_returns_none_when_no_active() {
        let text = "Credit X\n 已過期\t\n—\n$10\n\t$20\t\n";
        assert_eq!(parse_google(text), None);
    }
}
