use crate::error::ProxyError;
use crate::state::AppState;
use axum::extract::State;
use axum::routing::{get, post};
use axum::{Json, Router};
use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/segment", post(segment))
        .route("/detect", post(detect))
        .route("/caption", post(caption))
        .route("/batch-segment", post(batch_segment))
        .route("/models", get(list_models))
        .route("/models/load", post(load_model))
        .route("/models/unload", post(unload_model))
        .with_state(state)
}

#[derive(Debug, Deserialize)]
pub struct SegmentRequest {
    pub file_path: String,
    pub prompt: String,
    #[serde(default = "default_task")]
    pub task: String,
}

fn default_task() -> String { "referring".to_string() }

#[derive(Debug, Deserialize)]
pub struct DetectRequest {
    pub file_path: String,
    pub prompt: String,
}

#[derive(Debug, Deserialize)]
pub struct CaptionRequest {
    pub file_path: String,
    #[serde(default)]
    pub prompt: String,
    #[serde(default = "default_detail")]
    pub detail: String,
}

fn default_detail() -> String { "brief".to_string() }

#[derive(Debug, Deserialize)]
pub struct BatchSegmentRequest {
    pub file_path: String,
    pub prompts: Vec<String>,
}

#[derive(Debug, Deserialize)]
pub struct ModelRequest {
    pub model: String,
}

async fn health(State(state): State<AppState>) -> Json<Value> {
    let h = state.health.read().await;
    let last_error: Option<String> = if h.last_error.is_empty() {
        None
    } else {
        Some(h.last_error.clone())
    };
    Json(json!({
        "status": "ok",
        "service": "remote-node",
        "port": state.cfg.port,
        "remote_url": state.cfg.remote_url,
        "remote_healthy": h.healthy,
        "remote_last_check": h.last_check,
        "remote_last_error": last_error,
    }))
}

async fn assert_remote_healthy(state: &AppState) -> Result<(), ProxyError> {
    let h = state.health.read().await;
    if h.healthy {
        return Ok(());
    }
    let mut detail = String::new();
    if !h.last_error.is_empty() {
        detail.push_str(&format!(" Last error: {}", h.last_error));
    }
    detail.push_str(&format!(" Remote URL: {}", state.cfg.remote_url));
    Err(ProxyError::RemoteUnhealthy(detail))
}

fn read_file_b64(file_path: &str) -> Result<String, ProxyError> {
    let resolved = PathBuf::from(shellexpand::tilde(file_path).into_owned());
    let resolved = resolved.canonicalize()
        .map_err(|_| ProxyError::FileNotFound(file_path.to_string()))?;
    if !resolved.is_file() {
        return Err(ProxyError::FileNotFound(file_path.to_string()));
    }
    let bytes = std::fs::read(&resolved)?;
    Ok(B64.encode(bytes))
}

fn save_b64_file(out_dir: &Path, filename: &str, b64: &str) -> Result<String, ProxyError> {
    std::fs::create_dir_all(out_dir)?;
    let out_path = out_dir.join(filename);
    let bytes = B64.decode(b64)?;
    std::fs::write(&out_path, bytes)?;
    Ok(out_path.to_string_lossy().into_owned())
}

fn make_output_filename(prefix: &str, ext: &str) -> String {
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("{prefix}_{ts}{ext}")
}

async fn forward_json(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<Value, ProxyError> {
    let url = format!("{}{}", state.cfg.remote_url, path);
    let mut req = state.http.request(method, &url);
    if let Some(b) = body {
        req = req.json(&b);
    }
    let resp = req.send().await.map_err(|e| {
        if e.is_timeout() {
            ProxyError::RemoteTimeout(state.cfg.timeout)
        } else if e.is_connect() {
            ProxyError::RemoteConnect(state.cfg.remote_url.clone())
        } else {
            ProxyError::RemoteConnect(format!("{}: {}", state.cfg.remote_url, e))
        }
    })?;
    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(ProxyError::RemoteStatus {
            status: status.as_u16(),
            body,
        });
    }
    let value: Value = resp.json().await.map_err(|e| ProxyError::RemoteStatus {
        status: 502,
        body: format!("invalid JSON from remote: {e}"),
    })?;
    Ok(value)
}

async fn segment(
    State(state): State<AppState>,
    Json(req): Json<SegmentRequest>,
) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let image_b64 = read_file_b64(&req.file_path)?;
    let payload = json!({ "image": image_b64, "text": req.prompt });
    let _ = req.task; // parity: accepted but remote ignores
    let mut result = forward_json(&state, reqwest::Method::POST, "/segment", Some(payload)).await?;
    if let Some(obj) = result.as_object_mut() {
        if let Some(Value::String(b64)) = obj.remove("mask_base64") {
            let filename = make_output_filename("mask", ".png");
            let saved = save_b64_file(&state.output_dir, &filename, &b64)?;
            obj.insert("mask_path".to_string(), Value::String(saved));
        }
    }
    Ok(Json(result))
}

async fn detect(
    State(state): State<AppState>,
    Json(req): Json<DetectRequest>,
) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let image_b64 = read_file_b64(&req.file_path)?;
    let payload = json!({ "image": image_b64, "text": req.prompt });
    let result = forward_json(&state, reqwest::Method::POST, "/detect", Some(payload)).await?;
    Ok(Json(result))
}

async fn caption(
    State(state): State<AppState>,
    Json(req): Json<CaptionRequest>,
) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let image_b64 = read_file_b64(&req.file_path)?;
    let text = if !req.prompt.is_empty() {
        req.prompt.clone()
    } else if req.detail == "detailed" {
        "Describe this image in detail.".to_string()
    } else {
        "What is in this image?".to_string()
    };
    let payload = json!({ "image": image_b64, "text": text });
    let result = forward_json(&state, reqwest::Method::POST, "/caption", Some(payload)).await?;
    Ok(Json(result))
}

async fn batch_segment(
    State(state): State<AppState>,
    Json(req): Json<BatchSegmentRequest>,
) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let image_b64 = read_file_b64(&req.file_path)?;
    let payload = json!({ "image": image_b64, "prompts": req.prompts });
    let mut result = forward_json(&state, reqwest::Method::POST, "/batch-segment", Some(payload)).await?;

    if let Some(obj) = result.as_object_mut() {
        if let Some(Value::Object(results)) = obj.get_mut("results") {
            let keys: Vec<String> = results.keys().cloned().collect();
            for key in keys {
                if let Some(Value::Object(seg)) = results.get_mut(&key) {
                    if let Some(Value::String(b64)) = seg.remove("mask_base64") {
                        let safe: String = key.replace(' ', "_").chars().take(30).collect();
                        let filename = make_output_filename(&format!("mask_{safe}"), ".png");
                        let saved = save_b64_file(&state.output_dir, &filename, &b64)?;
                        seg.insert("mask_path".to_string(), Value::String(saved));
                    }
                }
            }
        }
        if let Some(Value::String(b64)) = obj.remove("composite_mask_base64") {
            let filename = make_output_filename("composite", ".png");
            let saved = save_b64_file(&state.output_dir, &filename, &b64)?;
            obj.insert("composite_mask_path".to_string(), Value::String(saved));
        }
    }
    Ok(Json(result))
}

async fn list_models(State(state): State<AppState>) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let result = forward_json(&state, reqwest::Method::GET, "/models", None).await?;
    Ok(Json(result))
}

async fn load_model(
    State(state): State<AppState>,
    Json(req): Json<ModelRequest>,
) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let payload = json!({ "model": req.model });
    let result = forward_json(&state, reqwest::Method::POST, "/models/load", Some(payload)).await?;
    Ok(Json(result))
}

async fn unload_model(
    State(state): State<AppState>,
    Json(req): Json<ModelRequest>,
) -> Result<Json<Value>, ProxyError> {
    assert_remote_healthy(&state).await?;
    let payload = json!({ "model": req.model });
    let result = forward_json(&state, reqwest::Method::POST, "/models/unload", Some(payload)).await?;
    Ok(Json(result))
}

