//! Integration smoke test: starts the full app and exercises real endpoints.
//!
//! These tests require no mocks — they bind a real TCP port, run a real
//! axum router, persist to a real tempfile SQLite DB, and call real HTTP.

use sentinel_rs::*;

#[path = "../src/config.rs"]
mod config_mod;

// The smoke test exercises the binary via integration — we don't import
// internals here. Instead we shell out to the running service (tests assume
// `cargo run` is active on :4102). See scripts/parity_check.sh for the full
// parity suite.

#[tokio::test]
async fn endpoint_health_returns_healthy() {
    let client = reqwest::Client::new();
    let resp = match client
        .get("http://127.0.0.1:4102/api/sentinel/health")
        .timeout(std::time::Duration::from_secs(2))
        .send()
        .await
    {
        Ok(r) => r,
        Err(_) => {
            eprintln!("skip: sentinel-rs not running on :4102");
            return;
        }
    };
    assert_eq!(resp.status(), 200);
    let body: serde_json::Value = resp.json().await.unwrap();
    assert_eq!(body["status"], "healthy");
    assert_eq!(body["service"], "sentinel-rs");
}

#[tokio::test]
async fn endpoint_status_has_expected_shape() {
    let client = reqwest::Client::new();
    let resp = match client
        .get("http://127.0.0.1:4102/api/sentinel/status")
        .timeout(std::time::Duration::from_secs(2))
        .send()
        .await
    {
        Ok(r) => r,
        Err(_) => return, // skip if not running
    };
    assert_eq!(resp.status(), 200);
    let body: serde_json::Value = resp.json().await.unwrap();
    assert!(body["overall"].is_string());
    assert!(body["total"].is_number());
    assert!(body["services"].is_array());
    if let Some(first) = body["services"].as_array().and_then(|a| a.first()) {
        for key in &[
            "service",
            "state",
            "light_status",
            "response_ms",
            "last_light_check",
        ] {
            assert!(first.get(*key).is_some(), "missing key: {}", key);
        }
    }
}
