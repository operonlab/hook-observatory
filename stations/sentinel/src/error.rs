use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

#[derive(Debug, thiserror::Error)]
pub enum SentinelError {
    #[error("not found: {0}")]
    NotFound(String),

    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("db error: {0}")]
    Db(#[from] sqlx::Error),

    #[error("internal: {0}")]
    Internal(#[from] anyhow::Error),
}

impl IntoResponse for SentinelError {
    fn into_response(self) -> Response {
        let (status, msg) = match &self {
            SentinelError::NotFound(m) => (StatusCode::NOT_FOUND, m.clone()),
            SentinelError::BadRequest(m) => (StatusCode::BAD_REQUEST, m.clone()),
            SentinelError::Db(_) | SentinelError::Internal(_) => {
                tracing::error!(error = %self, "internal error");
                (StatusCode::INTERNAL_SERVER_ERROR, "internal error".into())
            }
        };
        (status, Json(json!({ "error": msg }))).into_response()
    }
}

pub type Result<T> = std::result::Result<T, SentinelError>;
