//! Integration smoke test: exercises real endpoints against a running service.
//!
//! These tests require no mocks. They skip gracefully if sentinel
//! is not running on :4102. For the full comparison suite see
//! scripts/parity_check.sh.

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
            eprintln!("skip: sentinel not running on :4102");
            return;
        }
    };
    assert_eq!(resp.status(), 200);
    let body: serde_json::Value = resp.json().await.unwrap();
    assert_eq!(body["status"], "healthy");
    assert_eq!(body["service"], "sentinel");
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
        Err(_) => return,
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
