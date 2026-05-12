//! Bark push notification client.
//!
//! Protocol: GET `{bark_server}/{device_key}/{encoded_title}/{encoded_body}`
//! Success:  `{"code": 200, ...}`
//!
//! Mirrors `stations/auto-survey/src/auto_survey/notify.py`.

use anyhow::Result;
use serde::Deserialize;

use crate::config::Settings;

#[derive(Debug, Deserialize)]
struct BarkResponse {
    code: i64,
}

/// Send a Bark push notification.
///
/// Returns `Ok(true)` when the server acknowledges `{"code": 200}`.
/// Returns `Ok(false)` on network success but non-200 Bark code.
/// Returns `Err` only on network / parse failure.
pub async fn send_bark(
    client: &reqwest::Client,
    cfg: &Settings,
    title: &str,
    body: &str,
) -> Result<bool> {
    let encoded_title = urlencoding::encode(title);
    let encoded_body = urlencoding::encode(body);

    let url = format!(
        "{server}/{key}/{title}/{body}",
        server = cfg.bark_server.trim_end_matches('/'),
        key = cfg.bark_device_key,
        title = encoded_title,
        body = encoded_body,
    );

    tracing::debug!("[bark] GET {}", url);

    let resp = match client.get(&url).send().await {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!("[bark] request failed: {}", e);
            return Ok(false);
        }
    };

    let status = resp.status();
    let text = resp.text().await.unwrap_or_default();

    if !status.is_success() {
        tracing::warn!("[bark] HTTP {} — {}", status, &text[..text.len().min(200)]);
        return Ok(false);
    }

    match serde_json::from_str::<BarkResponse>(&text) {
        Ok(r) if r.code == 200 => {
            tracing::debug!("[bark] delivered");
            Ok(true)
        }
        Ok(r) => {
            tracing::warn!("[bark] server code {}: {}", r.code, &text[..text.len().min(200)]);
            Ok(false)
        }
        Err(e) => {
            tracing::warn!("[bark] JSON parse error: {} — body: {}", e, &text[..text.len().min(200)]);
            Ok(false)
        }
    }
}
