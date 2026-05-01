//! LLM fallback chain: LiteLLM → Gemini REST → None.
//!
//! Mirrors the Python reporter's routing intent but uses reqwest with a 60s
//! timeout and a single retry per provider. Returns `Ok(None)` when all
//! providers fail or are not configured (caller falls back to raw stats).

use anyhow::Result;
use serde_json::{json, Value};
use std::time::Duration;

use crate::config::Settings;

const TIMEOUT: Duration = Duration::from_secs(60);
const RETRIES: u32 = 1;
const LITELLM_MODEL: &str = "grok-4.1-fast";
const GEMINI_MODEL: &str = "gemini-2.0-flash";
const TEMPERATURE: f64 = 0.3;
const MAX_TOKENS: u32 = 4096;

/// Run the fallback chain. Returns `Ok((Some(text), engine))` on success or
/// `Ok((None, "offline"))` if every provider failed.
pub async fn generate(cfg: &Settings, prompt: &str) -> Result<(Option<String>, &'static str)> {
    let client = match reqwest::Client::builder().timeout(TIMEOUT).build() {
        Ok(c) => c,
        Err(e) => {
            tracing::warn!(error=%e, "reqwest client build failed");
            return Ok((None, "offline"));
        }
    };

    // 1) LiteLLM
    if let (Some(url), Some(token)) = (cfg.litellm_url.as_ref(), cfg.litellm_token.as_ref()) {
        match try_with_retry(RETRIES, || call_litellm(&client, url, token, prompt)).await {
            Ok(Some(text)) => return Ok((Some(text), "litellm")),
            Ok(None) => tracing::warn!("litellm returned empty content"),
            Err(e) => tracing::warn!(error=%e, "litellm failed, falling back to gemini"),
        }
    } else {
        tracing::debug!("litellm_url/token not configured, skipping");
    }

    // 2) Gemini REST
    if let Some(key) = cfg.gemini_api_key.as_ref() {
        match try_with_retry(RETRIES, || call_gemini(&client, key, prompt)).await {
            Ok(Some(text)) => return Ok((Some(text), "gemini")),
            Ok(None) => tracing::warn!("gemini returned empty content"),
            Err(e) => tracing::warn!(error=%e, "gemini failed"),
        }
    } else {
        tracing::debug!("gemini_api_key not configured, skipping");
    }

    Ok((None, "offline"))
}

async fn try_with_retry<F, Fut>(retries: u32, mut f: F) -> Result<Option<String>>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<Option<String>>>,
{
    let mut last_err: Option<anyhow::Error> = None;
    for attempt in 0..=retries {
        match f().await {
            Ok(v) => return Ok(v),
            Err(e) => {
                tracing::debug!(attempt, error=%e, "llm call failed, retrying");
                last_err = Some(e);
            }
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("unknown llm error")))
}

async fn call_litellm(
    client: &reqwest::Client,
    base_url: &str,
    token: &str,
    prompt: &str,
) -> Result<Option<String>> {
    let url = format!("{}/v1/chat/completions", base_url.trim_end_matches('/'));
    let payload = json!({
        "model": LITELLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    });

    let resp = client
        .post(&url)
        .bearer_auth(token)
        .json(&payload)
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("litellm http {}: {}", status, truncate(&body, 200));
    }

    let body: Value = resp.json().await?;
    let text = body
        .get("choices")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("message"))
        .and_then(|m| m.get("content"))
        .and_then(|v| v.as_str())
        .map(str::to_string);
    Ok(text.filter(|s| !s.trim().is_empty()))
}

async fn call_gemini(
    client: &reqwest::Client,
    api_key: &str,
    prompt: &str,
) -> Result<Option<String>> {
    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}",
        GEMINI_MODEL, api_key
    );
    let payload = json!({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": TEMPERATURE,
            "maxOutputTokens": MAX_TOKENS,
        }
    });

    let resp = client.post(&url).json(&payload).send().await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("gemini http {}: {}", status, truncate(&body, 200));
    }

    let body: Value = resp.json().await?;
    let text = body
        .get("candidates")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("content"))
        .and_then(|c| c.get("parts"))
        .and_then(|p| p.get(0))
        .and_then(|p| p.get("text"))
        .and_then(|v| v.as_str())
        .map(str::to_string);
    Ok(text.filter(|s| !s.trim().is_empty()))
}

fn truncate(s: &str, n: usize) -> String {
    if s.len() <= n {
        s.to_string()
    } else {
        format!("{}…", &s[..n])
    }
}
