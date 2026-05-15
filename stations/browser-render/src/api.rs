//! HTTP route handlers.

use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use browser_render::config::Config;
use browser_render::render::{self, RenderRequest, RenderResult};

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
}

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub version: &'static str,
    pub chromium_path: Option<String>,
}

pub async fn healthz(State(_st): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        version: env!("CARGO_PKG_VERSION"),
        chromium_path: browser_render::flags::find_chrome(),
    })
}

#[derive(Serialize)]
pub struct ErrorBody {
    pub error: String,
}

pub async fn render_endpoint(
    State(_st): State<AppState>,
    Json(req): Json<RenderRequest>,
) -> Result<Json<RenderResult>, (StatusCode, Json<ErrorBody>)> {
    match render::render(req).await {
        Ok(r) => Ok(Json(r)),
        Err(e) => {
            tracing::error!("render failed: {e:?}");
            Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorBody {
                    error: format!("{e:#}"),
                }),
            ))
        }
    }
}

#[derive(Deserialize)]
pub struct ShutdownReq {
    #[serde(default)]
    pub token: Option<String>,
}

pub async fn shutdown(
    State(_st): State<AppState>,
    Json(_body): Json<ShutdownReq>,
) -> &'static str {
    tracing::warn!("shutdown requested via /shutdown");
    // Schedule actual exit so the HTTP response can flush first.
    tokio::spawn(async {
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        std::process::exit(0);
    });
    "shutting down"
}
