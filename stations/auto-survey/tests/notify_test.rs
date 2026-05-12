//! Tests for notify::send_bark — mocks the Bark endpoint with wiremock.

use auto_survey::notify;
use wiremock::matchers::{method, path_regex};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn make_settings(bark_server: &str) -> auto_survey::config::Settings {
    let mut cfg = auto_survey::config::Settings::from_env();
    // Override at runtime by building a test-only value
    auto_survey::config::Settings {
        bark_server: bark_server.to_string(),
        bark_device_key: "TEST_DEVICE_KEY".to_string(),
        ..cfg
    }
}

fn make_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .expect("client")
}

// ---------------------------------------------------------------------------
// 1. Bark returns {"code": 200} → Ok(true)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_send_bark_success() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path_regex("TEST_DEVICE_KEY"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"code": 200, "message": "success"})),
        )
        .mount(&server)
        .await;

    let client = make_client();
    let cfg = make_settings(&server.uri());
    let result = notify::send_bark(&client, &cfg, "Test Title", "Test body").await;

    assert!(result.is_ok());
    assert_eq!(result.unwrap(), true);
}

// ---------------------------------------------------------------------------
// 2. Bark returns {"code": 400} → Ok(false)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_send_bark_non_200_code() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path_regex("TEST_DEVICE_KEY"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"code": 400, "message": "bad request"})),
        )
        .mount(&server)
        .await;

    let client = make_client();
    let cfg = make_settings(&server.uri());
    let result = notify::send_bark(&client, &cfg, "Title", "Body").await;

    assert!(result.is_ok());
    assert_eq!(result.unwrap(), false);
}

// ---------------------------------------------------------------------------
// 3. HTTP 500 → Ok(false) (not Err — network succeeded but server errored)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_send_bark_http_error() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path_regex("TEST_DEVICE_KEY"))
        .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
        .mount(&server)
        .await;

    let client = make_client();
    let cfg = make_settings(&server.uri());
    let result = notify::send_bark(&client, &cfg, "Title", "Body").await;

    assert!(result.is_ok());
    assert_eq!(result.unwrap(), false);
}

// ---------------------------------------------------------------------------
// 4. URL encoding: special chars in title/body must be percent-encoded
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_send_bark_url_encoding() {
    let server = MockServer::start().await;

    // The mock matches any path containing the device key
    Mock::given(method("GET"))
        .and(path_regex("TEST_DEVICE_KEY"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"code": 200})),
        )
        .mount(&server)
        .await;

    let client = make_client();
    let cfg = make_settings(&server.uri());
    // Title with spaces and Chinese characters
    let result = notify::send_bark(&client, &cfg, "自動簽到 成功", "URL: https://example.com/test?a=1&b=2").await;

    assert!(result.is_ok());
    assert_eq!(result.unwrap(), true);
}
