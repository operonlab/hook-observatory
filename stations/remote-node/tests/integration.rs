//! Integration tests for remote-node
//!
//! Strategy: wiremock acts as the Windows GPU server (外部 I/O boundary — mock OK per 六鐵律 #5).
//! A real Rust binary is spawned via `cargo run --release`, polled on /health until ready,
//! then exercised via HTTP requests. Process is killed after each test group.
//!
//! # Edge gaps (誠實揭露)
//! 1. `health_interval` is 30 s in config — tests inject a 1 s interval to avoid slow convergence.
//!    If the Rust impl ignores the interval field, health state may lag and tests flap.
//! 2. Timeout-to-504 relies on wiremock's `Delay` feature. If reqwest timeout < delay, the
//!    Rust binary must propagate 504; if it returns 503 or 500 instead, test will fail.
//! 3. batch-segment with 0 prompts is not tested (empty results map).
//! 4. Filenames with non-ASCII characters in prompt_key truncation are not tested.
//! 5. The `task` field in SegmentRequest is not verified on the wire (wiremock matches any body).
//! 6. concurrent requests to unhealthy remote are not tested.
//! 7. Remote returning HTTP 4xx (e.g. 422) is not tested — Python behaviour is pass-through.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::{Value, json};
use tempfile::TempDir;
use wiremock::matchers::{body_json_schema, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

// ── Minimal 1×1 PNG (red pixel) as base64 ────────────────────────────────────
const MINI_PNG_B64: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC";

// ── Helper: decode MINI_PNG_B64 to raw bytes ─────────────────────────────────
fn mini_png_bytes() -> Vec<u8> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(MINI_PNG_B64)
        .expect("MINI_PNG_B64 is valid base64")
}

// ── Helper: write a real PNG file to a temp dir ──────────────────────────────
fn write_temp_png(dir: &TempDir) -> PathBuf {
    let p = dir.path().join("test_input.png");
    std::fs::write(&p, mini_png_bytes()).expect("write temp png");
    p
}

// ── Helper: write a minimal valid config.yaml ────────────────────────────────
fn write_test_config(dir: &TempDir, remote_url: &str, port: u16, output_dir: &str) -> PathBuf {
    let cfg = format!(
        "port: {}\nhost: \"127.0.0.1\"\nremote_url: \"{}\"\nhealth_interval: 1\ntimeout: 5\noutput_dir: \"{}\"\n",
        port, remote_url, output_dir
    );
    let p = dir.path().join("config.yaml");
    std::fs::write(&p, cfg).expect("write config");
    p
}

// ── Helper: pick a free port ─────────────────────────────────────────────────
fn free_port() -> u16 {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
    listener.local_addr().expect("local_addr").port()
}

// ── Helper: spawn the Rust binary and wait until /health responds ─────────────
async fn spawn_remote_node(config_path: &PathBuf) -> tokio::process::Child {
    // Build binary path (release build must exist before running tests)
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));

    // Use the pre-built release binary directly. Running `cargo run` per test
    // serialises on the Cargo lock; 18 parallel tests then time-out waiting for
    // rebuild checks. Assume `cargo build --release` ran before `cargo test`.
    let bin = manifest_dir.join("target/release/remote-node");
    let mut child = tokio::process::Command::new(&bin)
        .args([
            "--config",
            config_path.to_str().unwrap(),
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .unwrap_or_else(|e| panic!("spawn {}: {}", bin.display(), e));

    // Parse port from config (re-read the file)
    let cfg_text = std::fs::read_to_string(config_path).expect("read config");
    let port: u16 = cfg_text
        .lines()
        .find(|l| l.starts_with("port:"))
        .and_then(|l| l.split(':').nth(1))
        .and_then(|v| v.trim().parse().ok())
        .expect("parse port from config");

    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{}/health", port);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(60);

    loop {
        if tokio::time::Instant::now() > deadline {
            let _ = child.kill().await;
            panic!("remote-node did not start within 60s on port {}", port);
        }
        if let Ok(resp) = client.get(&url).timeout(Duration::from_secs(1)).send().await {
            if resp.status().is_success() {
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    child
}

// ── Helper: kill process and await ───────────────────────────────────────────
async fn kill_proc(mut child: tokio::process::Child) {
    let _ = child.kill().await;
    let _ = child.wait().await;
}

// ── Helper: build reqwest client with short timeout ──────────────────────────
fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .expect("build client")
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUP 1: Health endpoint
// ═══════════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn health_remote_healthy_true_when_remote_200() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        // Persistent — answer every poll
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;

    // Wait up to 3 s for health_interval (1 s) to fire at least once
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .get(format!("http://127.0.0.1:{}/health", port))
        .send()
        .await
        .expect("GET /health");

    assert_eq!(resp.status(), 200, "proxy /health should be 200");
    let body: Value = resp.json().await.expect("parse body");
    assert_eq!(
        body["remote_healthy"], json!(true),
        "remote_healthy should be true when remote responds 200"
    );
    assert!(
        body["remote_last_error"].is_null(),
        "remote_last_error should be null when healthy, got: {}",
        body["remote_last_error"]
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn health_remote_healthy_false_when_remote_5xx() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(503).set_body_string("unhealthy"))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .get(format!("http://127.0.0.1:{}/health", port))
        .send()
        .await
        .expect("GET /health");

    assert_eq!(resp.status(), 200, "proxy /health itself should still be 200");
    let body: Value = resp.json().await.expect("parse body");
    assert_eq!(
        body["remote_healthy"], json!(false),
        "remote_healthy should be false when remote returns 5xx"
    );
    let last_err = body["remote_last_error"].as_str().unwrap_or("");
    assert!(
        !last_err.is_empty(),
        "remote_last_error should be non-empty when remote is unhealthy"
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn health_remote_healthy_false_when_remote_unreachable() {
    // No mock server — use a port that is guaranteed closed
    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    // Point remote_url at a port that should not have anything listening
    let dead_port = free_port();
    let remote_url = format!("http://127.0.0.1:{}", dead_port);
    let cfg = write_test_config(&tmp, &remote_url, port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .get(format!("http://127.0.0.1:{}/health", port))
        .send()
        .await
        .expect("GET /health");

    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");
    assert_eq!(
        body["remote_healthy"], json!(false),
        "remote_healthy should be false when connection refused"
    );

    kill_proc(proc).await;
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUP 2: 503 gate — all endpoints reject when remote unhealthy
// ═══════════════════════════════════════════════════════════════════════════════

async fn setup_unhealthy_server() -> (MockServer, TempDir, u16) {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(503))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    // Spawn — we return only port; caller must hold tmp alive
    // (Can't return Child here without complex ownership; caller does this manually)
    (mock_server, tmp, port)
}

#[tokio::test]
async fn gate_503_all_endpoints_when_unhealthy() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(503))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let base = format!("http://127.0.0.1:{}", port);
    let c = client();

    // Create a dummy file path (doesn't matter — should hit 503 before file read)
    let dummy_path = "/nonexistent/path/img.png";

    let endpoints: Vec<(&str, Box<dyn Fn(&reqwest::Client) -> reqwest::RequestBuilder + Send + Sync>)> = vec![
        (
            "POST /segment",
            Box::new({
                let base = base.clone();
                move |c| {
                    c.post(format!("{}/segment", base))
                        .json(&json!({"file_path": dummy_path, "prompt": "cat"}))
                }
            }),
        ),
        (
            "POST /detect",
            Box::new({
                let base = base.clone();
                move |c| {
                    c.post(format!("{}/detect", base))
                        .json(&json!({"file_path": dummy_path, "prompt": "cat"}))
                }
            }),
        ),
        (
            "POST /caption",
            Box::new({
                let base = base.clone();
                move |c| {
                    c.post(format!("{}/caption", base))
                        .json(&json!({"file_path": dummy_path}))
                }
            }),
        ),
        (
            "POST /batch-segment",
            Box::new({
                let base = base.clone();
                move |c| {
                    c.post(format!("{}/batch-segment", base))
                        .json(&json!({"file_path": dummy_path, "prompts": ["cat"]}))
                }
            }),
        ),
        (
            "GET /models",
            Box::new({
                let base = base.clone();
                move |c| c.get(format!("{}/models", base))
            }),
        ),
        (
            "POST /models/load",
            Box::new({
                let base = base.clone();
                move |c| {
                    c.post(format!("{}/models/load", base))
                        .json(&json!({"model": "sam"}))
                }
            }),
        ),
        (
            "POST /models/unload",
            Box::new({
                let base = base.clone();
                move |c| {
                    c.post(format!("{}/models/unload", base))
                        .json(&json!({"model": "sam"}))
                }
            }),
        ),
    ];

    for (name, builder) in &endpoints {
        let resp = builder(&c).send().await.expect(name);
        assert_eq!(
            resp.status(),
            503,
            "endpoint {} should return 503 when remote is unhealthy",
            name
        );
        let body: Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("");
        assert!(
            detail.to_lowercase().contains("unreachable")
                || detail.to_lowercase().contains("unhealthy")
                || detail.to_lowercase().contains("windows")
                || detail.to_lowercase().contains("gpu"),
            "503 detail for {} should mention unreachability, got: {:?}",
            name,
            detail
        );
    }

    kill_proc(proc).await;
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUP 3: 404 for missing file_path
// ═══════════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn file_not_found_returns_404_with_filename_in_detail() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let base = format!("http://127.0.0.1:{}", port);
    let c = client();
    let missing = "/absolutely/nonexistent/ghost_image_xyz.png";

    // /segment
    {
        let resp = c
            .post(format!("{}/segment", base))
            .json(&json!({"file_path": missing, "prompt": "cat"}))
            .send()
            .await
            .expect("POST /segment");
        assert_eq!(resp.status(), 404, "/segment should 404 for missing file");
        let body: Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("");
        assert!(
            detail.contains("ghost_image_xyz"),
            "/segment 404 detail should contain filename, got: {:?}",
            detail
        );
    }

    // /detect
    {
        let resp = c
            .post(format!("{}/detect", base))
            .json(&json!({"file_path": missing, "prompt": "dog"}))
            .send()
            .await
            .expect("POST /detect");
        assert_eq!(resp.status(), 404, "/detect should 404 for missing file");
        let body: Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("");
        assert!(
            detail.contains("ghost_image_xyz"),
            "/detect 404 detail should contain filename"
        );
    }

    // /caption
    {
        let resp = c
            .post(format!("{}/caption", base))
            .json(&json!({"file_path": missing}))
            .send()
            .await
            .expect("POST /caption");
        assert_eq!(resp.status(), 404, "/caption should 404 for missing file");
        let body: Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("");
        assert!(
            detail.contains("ghost_image_xyz"),
            "/caption 404 detail should contain filename"
        );
    }

    // /batch-segment
    {
        let resp = c
            .post(format!("{}/batch-segment", base))
            .json(&json!({"file_path": missing, "prompts": ["cat", "dog"]}))
            .send()
            .await
            .expect("POST /batch-segment");
        assert_eq!(
            resp.status(),
            404,
            "/batch-segment should 404 for missing file"
        );
        let body: Value = resp.json().await.unwrap_or_default();
        let detail = body["detail"].as_str().unwrap_or("");
        assert!(
            detail.contains("ghost_image_xyz"),
            "/batch-segment 404 detail should contain filename"
        );
    }

    kill_proc(proc).await;
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUP 4: Successful paths
// ═══════════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn segment_success_removes_base64_adds_mask_path_with_correct_bytes() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path("/segment"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"mask_base64": MINI_PNG_B64})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/segment", port))
        .json(&json!({"file_path": img_path.to_str().unwrap(), "prompt": "cat"}))
        .send()
        .await
        .expect("POST /segment");

    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");

    // mask_base64 must be removed
    assert!(
        body.get("mask_base64").is_none(),
        "mask_base64 must be removed from response, got body: {}",
        body
    );

    // mask_path must be present and point to an existing file
    let mask_path = body["mask_path"]
        .as_str()
        .expect("mask_path must be a string");
    let mask_file = std::path::Path::new(mask_path);
    assert!(
        mask_file.exists(),
        "mask_path '{}' must point to an existing file",
        mask_path
    );

    // File content must equal the decoded PNG bytes (not just "some file exists")
    let saved_bytes = std::fs::read(mask_file).expect("read mask file");
    assert_eq!(
        saved_bytes,
        mini_png_bytes(),
        "mask file bytes must equal decoded MINI_PNG_B64"
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn detect_passthrough_returns_boxes() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path("/detect"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"boxes": [[10, 20, 100, 200]]})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/detect", port))
        .json(&json!({"file_path": img_path.to_str().unwrap(), "prompt": "cat"}))
        .send()
        .await
        .expect("POST /detect");

    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");
    assert!(
        body["boxes"].is_array(),
        "detect should passthrough boxes array"
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn caption_passthrough_returns_text() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path("/caption"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"text": "a red pixel image"})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/caption", port))
        .json(&json!({"file_path": img_path.to_str().unwrap(), "prompt": "describe it"}))
        .send()
        .await
        .expect("POST /caption");

    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");
    assert_eq!(
        body["text"].as_str().unwrap_or(""),
        "a red pixel image",
        "caption should passthrough text field"
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn batch_segment_saves_per_prompt_masks_and_composite() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path("/batch-segment"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "results": {
                "cat": {"mask_base64": MINI_PNG_B64},
                "dog": {"mask_base64": MINI_PNG_B64}
            },
            "composite_mask_base64": MINI_PNG_B64
        })))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/batch-segment", port))
        .json(&json!({
            "file_path": img_path.to_str().unwrap(),
            "prompts": ["cat", "dog"]
        }))
        .send()
        .await
        .expect("POST /batch-segment");

    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");

    // composite_mask_base64 must be removed, composite_mask_path must exist
    assert!(
        body.get("composite_mask_base64").is_none(),
        "composite_mask_base64 must be removed"
    );
    let comp_path = body["composite_mask_path"]
        .as_str()
        .expect("composite_mask_path must be present");
    let comp_file = std::path::Path::new(comp_path);
    assert!(comp_file.exists(), "composite_mask_path must exist on disk");
    assert_eq!(
        std::fs::read(comp_file).expect("read composite"),
        mini_png_bytes(),
        "composite mask bytes must match decoded base64"
    );

    // Per-prompt masks
    let results = body["results"].as_object().expect("results must be object");
    for prompt in ["cat", "dog"] {
        let seg = &results[prompt];
        assert!(
            seg.get("mask_base64").is_none(),
            "mask_base64 for '{}' must be removed",
            prompt
        );
        let mp = seg["mask_path"]
            .as_str()
            .expect("mask_path must be present for each prompt");
        let mf = std::path::Path::new(mp);
        assert!(mf.exists(), "mask_path for '{}' must exist on disk", prompt);
        assert_eq!(
            std::fs::read(mf).expect("read mask"),
            mini_png_bytes(),
            "mask bytes for '{}' must match decoded base64",
            prompt
        );
    }

    kill_proc(proc).await;
}

#[tokio::test]
async fn models_list_passthrough() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("GET"))
        .and(path("/models"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"models": ["sam", "yolo"]})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .get(format!("http://127.0.0.1:{}/models", port))
        .send()
        .await
        .expect("GET /models");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");
    assert!(body["models"].is_array(), "models should be an array");

    kill_proc(proc).await;
}

#[tokio::test]
async fn models_load_passthrough() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/models/load"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"status": "loaded", "model": "sam"})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/models/load", port))
        .json(&json!({"model": "sam"}))
        .send()
        .await
        .expect("POST /models/load");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");
    // Invariant: response is a valid JSON object
    assert!(body.is_object(), "models/load should return JSON object");

    kill_proc(proc).await;
}

#[tokio::test]
async fn models_unload_passthrough() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/models/unload"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"status": "unloaded", "model": "sam"})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/models/unload", port))
        .json(&json!({"model": "sam"}))
        .send()
        .await
        .expect("POST /models/unload");
    assert_eq!(resp.status(), 200);
    let body: Value = resp.json().await.expect("parse body");
    assert!(body.is_object(), "models/unload should return JSON object");

    kill_proc(proc).await;
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUP 5: Caption detail branch
// ═══════════════════════════════════════════════════════════════════════════════

/// Captures the body sent to the mock server and checks `text` field.
/// Uses a shared atomic string via Arc<Mutex> approach — but wiremock's
/// `received_requests()` is cleaner: inspect after the call.
#[tokio::test]
async fn caption_detail_detailed_sends_correct_text() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/caption"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"text": "a detailed desc"})))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/caption", port))
        .json(&json!({
            "file_path": img_path.to_str().unwrap(),
            "prompt": "",
            "detail": "detailed"
        }))
        .send()
        .await
        .expect("POST /caption detailed");
    assert_eq!(resp.status(), 200);

    // Inspect what the mock server received
    let reqs = mock_server.received_requests().await.expect("received_requests");
    let caption_req = reqs
        .iter()
        .find(|r| r.url.path() == "/caption")
        .expect("should have received a /caption request");
    let body: Value = serde_json::from_slice(&caption_req.body).expect("parse request body");
    let text = body["text"].as_str().unwrap_or("");
    assert_eq!(
        text, "Describe this image in detail.",
        "detail='detailed' + empty prompt should send 'Describe this image in detail.' \
        (Python main.py line 274–276), got: {:?}",
        text
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn caption_detail_brief_sends_correct_text() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/caption"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"text": "brief desc"})))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    client()
        .post(format!("http://127.0.0.1:{}/caption", port))
        .json(&json!({
            "file_path": img_path.to_str().unwrap(),
            "prompt": "",
            "detail": "brief"
        }))
        .send()
        .await
        .expect("POST /caption brief");

    let reqs = mock_server.received_requests().await.expect("received_requests");
    let caption_req = reqs
        .iter()
        .find(|r| r.url.path() == "/caption")
        .expect("should have received /caption");
    let body: Value = serde_json::from_slice(&caption_req.body).expect("parse request body");
    let text = body["text"].as_str().unwrap_or("");
    assert_eq!(
        text, "What is in this image?",
        "detail='brief' + empty prompt should send 'What is in this image?' \
        (Python main.py line 276), got: {:?}",
        text
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn caption_custom_prompt_passthrough() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/caption"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"text": "custom answer"})))
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    client()
        .post(format!("http://127.0.0.1:{}/caption", port))
        .json(&json!({
            "file_path": img_path.to_str().unwrap(),
            "prompt": "my custom prompt",
            "detail": "brief"
        }))
        .send()
        .await
        .expect("POST /caption custom prompt");

    let reqs = mock_server.received_requests().await.expect("received_requests");
    let caption_req = reqs
        .iter()
        .find(|r| r.url.path() == "/caption")
        .expect("should have received /caption");
    let body: Value = serde_json::from_slice(&caption_req.body).expect("parse request body");
    let text = body["text"].as_str().unwrap_or("");
    assert_eq!(
        text, "my custom prompt",
        "non-empty prompt should be sent verbatim to remote (Python main.py line 274), got: {:?}",
        text
    );

    kill_proc(proc).await;
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUP 6: Remote error handling
// ═══════════════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn remote_500_returns_500_with_remote_error_prefix() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/segment"))
        .respond_with(
            ResponseTemplate::new(500).set_body_string("internal gpu error"),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/segment", port))
        .json(&json!({"file_path": img_path.to_str().unwrap(), "prompt": "cat"}))
        .send()
        .await
        .expect("POST /segment 500");

    assert_eq!(
        resp.status(),
        500,
        "remote 500 should propagate as 500 (Python _forward_json line 155)"
    );
    let body: Value = resp.json().await.unwrap_or_default();
    let detail = body["detail"].as_str().unwrap_or("");
    assert!(
        detail.to_lowercase().contains("remote error") || detail.to_lowercase().contains("remote"),
        "500 detail should contain 'Remote error:' prefix (Python line 157), got: {:?}",
        detail
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn remote_timeout_returns_504() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    // Delay 8 s; config timeout is 5 s → should trigger timeout
    Mock::given(method("POST"))
        .and(path("/segment"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_delay(Duration::from_secs(8))
                .set_body_json(json!({"mask_base64": MINI_PNG_B64})),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    // Use a 15-second client timeout so we don't race the server timeout
    let c = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .unwrap();

    let resp = c
        .post(format!("http://127.0.0.1:{}/segment", port))
        .json(&json!({"file_path": img_path.to_str().unwrap(), "prompt": "cat"}))
        .send()
        .await
        .expect("POST /segment timeout");

    assert_eq!(
        resp.status(),
        504,
        "timeout should yield 504 (Python _forward_json line 150)"
    );

    kill_proc(proc).await;
}

#[tokio::test]
async fn remote_invalid_json_returns_502() {
    let mock_server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/health"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"status":"ok"})))
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/segment"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_string("this is not json {{{{")
                .insert_header("content-type", "application/json"),
        )
        .mount(&mock_server)
        .await;

    let tmp = TempDir::new().unwrap();
    let output_dir = tmp.path().join("out").to_string_lossy().to_string();
    let port = free_port();
    let cfg = write_test_config(&tmp, &mock_server.uri(), port, &output_dir);
    let img_path = write_temp_png(&tmp);

    let mut proc = spawn_remote_node(&cfg).await;
    tokio::time::sleep(Duration::from_secs(2)).await;

    let resp = client()
        .post(format!("http://127.0.0.1:{}/segment", port))
        .json(&json!({"file_path": img_path.to_str().unwrap(), "prompt": "cat"}))
        .send()
        .await
        .expect("POST /segment invalid json");

    assert_eq!(
        resp.status(),
        502,
        "invalid JSON from remote should yield 502"
    );

    kill_proc(proc).await;
}
