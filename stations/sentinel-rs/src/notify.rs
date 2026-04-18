use crate::models::CheckStatus;
use serde_json::Value;
use sqlx::SqlitePool;
use std::time::Duration;
use tokio::process::Command;

pub async fn macos_notify(title: &str, body: &str) {
    let script = format!(
        r#"display notification "{}" with title "{}""#,
        body.replace('"', "\\\""),
        title.replace('"', "\\\"")
    );
    let _ = tokio::time::timeout(
        Duration::from_secs(5),
        Command::new("osascript").arg("-e").arg(&script).output(),
    )
    .await;
}

pub async fn broadcast_webhooks(pool: &SqlitePool, event: &str, payload: &Value) {
    let rows: Vec<(String, String, String)> = match sqlx::query_as(
        "SELECT id, url, events FROM subscriptions WHERE active = 1",
    )
    .fetch_all(pool)
    .await
    {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!("fetch subscriptions failed: {}", e);
            return;
        }
    };

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();

    for (_id, url, events_json) in rows {
        let events: Vec<String> = serde_json::from_str(&events_json).unwrap_or_default();
        if !events.iter().any(|e| e == "*" || e == event) {
            continue;
        }
        let body = serde_json::json!({ "event": event, "payload": payload });
        let c = client.clone();
        let u = url.clone();
        tokio::spawn(async move {
            if let Err(e) = c.post(&u).json(&body).send().await {
                tracing::warn!(url = %u, "webhook post failed: {}", e);
            }
        });
    }
}

#[allow(dead_code)]
pub fn status_severity(status: &CheckStatus) -> &'static str {
    match status {
        CheckStatus::Healthy | CheckStatus::Operational | CheckStatus::Skipped => "info",
        CheckStatus::Degraded => "minor",
        CheckStatus::Unhealthy | CheckStatus::Timeout => "major",
        CheckStatus::MajorOutage => "critical",
    }
}
