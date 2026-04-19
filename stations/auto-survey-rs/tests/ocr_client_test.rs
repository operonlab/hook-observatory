//! Integration tests for ocr_client — uses wiremock to simulate the OCR service.

use auto_survey_rs::ocr_client;
use std::path::Path;
use wiremock::matchers::{method, path_regex, query_param_contains};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn make_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .expect("client")
}

// ---------------------------------------------------------------------------
// Helper: construct a fake image path for tests (file need not exist for URL build,
// but canonicalize will fail so we test with a real tmp file).
// ---------------------------------------------------------------------------

fn fake_png() -> std::path::PathBuf {
    let tmp = std::env::temp_dir().join("ocr_test_fake.png");
    std::fs::write(&tmp, b"FAKEPNG").unwrap();
    tmp
}

// ---------------------------------------------------------------------------
// 1. Happy path: service returns {"text": "hello", "engine": "apple", "lines": []}
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_extract_text_success() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path_regex("/extract"))
        .and(query_param_contains("engine", "apple"))
        .and(query_param_contains("languages", "zh-Hant"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({
                    "text": "https://www.surveycake.com/s/abc123",
                    "engine": "apple",
                    "lines": ["https://www.surveycake.com/s/abc123"]
                })),
        )
        .mount(&server)
        .await;

    let client = make_client();
    let img = fake_png();
    let result = ocr_client::extract_text(&client, &server.uri(), &img, &["zh-Hant", "zh-Hans", "en"]).await;

    assert!(result.is_ok(), "expected Ok, got: {:?}", result);
    assert!(result.unwrap().contains("surveycake.com"));
}

// ---------------------------------------------------------------------------
// 2. Service returns {"error": "unsupported engine"}  → Err
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_extract_text_service_error() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path_regex("/extract"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"error": "unsupported engine"})),
        )
        .mount(&server)
        .await;

    let client = make_client();
    let img = fake_png();
    let result = ocr_client::extract_text(&client, &server.uri(), &img, &[]).await;

    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(msg.contains("unsupported engine"), "unexpected error: {}", msg);
}

// ---------------------------------------------------------------------------
// 3. HTTP 500 → Err
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_extract_text_http_500() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path_regex("/extract"))
        .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
        .mount(&server)
        .await;

    let client = make_client();
    let img = fake_png();
    let result = ocr_client::extract_text(&client, &server.uri(), &img, &["zh-Hant"]).await;

    assert!(result.is_err());
    assert!(result.unwrap_err().to_string().contains("500"));
}

// ---------------------------------------------------------------------------
// 4. URL format: languages join + path encoding are correct
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_url_format_languages_default() {
    let server = MockServer::start().await;

    // Expect the default languages when slice is empty
    Mock::given(method("GET"))
        .and(path_regex("/extract"))
        .and(query_param_contains("languages", "zh-Hant"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"text": "ok", "engine": "apple", "lines": []})),
        )
        .mount(&server)
        .await;

    let client = make_client();
    let img = fake_png();
    // Empty languages → should default to zh-Hant,zh-Hans,en
    let result = ocr_client::extract_text(&client, &server.uri(), &img, &[]).await;
    assert!(result.is_ok());
}
