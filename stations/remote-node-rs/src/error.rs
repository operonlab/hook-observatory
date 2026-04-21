use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ProxyError {
    #[error("File not found: {0}")]
    FileNotFound(String),

    #[error("Windows GPU server is unreachable. {0}")]
    RemoteUnhealthy(String),

    #[error("Cannot connect to Windows GPU server at {0}")]
    RemoteConnect(String),

    #[error("Timeout ({0}s) waiting for Windows GPU server")]
    RemoteTimeout(u64),

    #[error("Remote error: {status} {body}")]
    RemoteStatus { status: u16, body: String },

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Base64 decode error: {0}")]
    Base64(#[from] base64::DecodeError),
}

impl IntoResponse for ProxyError {
    fn into_response(self) -> Response {
        let (status, detail) = match &self {
            ProxyError::FileNotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            ProxyError::RemoteUnhealthy(_) => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),
            ProxyError::RemoteConnect(_) => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),
            ProxyError::RemoteTimeout(_) => (StatusCode::GATEWAY_TIMEOUT, self.to_string()),
            ProxyError::RemoteStatus { status, body } => {
                let code = StatusCode::from_u16(*status).unwrap_or(StatusCode::BAD_GATEWAY);
                let trimmed: String = body.chars().take(500).collect();
                (code, format!("Remote error: {trimmed}"))
            }
            _ => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
        };
        (status, Json(json!({ "detail": detail }))).into_response()
    }
}
