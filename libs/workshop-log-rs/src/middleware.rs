//! Axum tower middleware: X-Request-ID propagation + span instrumentation.
//!
//! Feature gate: `axum-middleware`

use axum::{
    body::Body,
    http::{HeaderMap, HeaderValue, Request, Response},
};
use futures_util::future::BoxFuture;
use std::task::{Context, Poll};
use tower::{Layer, Service};
use uuid::Uuid;

// ── Public constructor ────────────────────────────────────────────────────────

/// Returns a [`tower::Layer`] that:
///
/// 1. Reads `X-Request-ID` from the incoming request header.
///    Accepts a 12-char lowercase hex string; any other value (or missing
///    header) causes a fresh 12-hex ID to be generated via UUID v4.
/// 2. Opens a `tracing::info_span!` with `request_id`, `method`, and `path`
///    fields so that all log events within the handler inherit those fields.
/// 3. Copies the `X-Request-ID` into the response header.
pub fn request_id_layer() -> RequestIdLayer {
    RequestIdLayer
}

// ── Layer ─────────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct RequestIdLayer;

impl<S> Layer<S> for RequestIdLayer {
    type Service = RequestIdService<S>;

    fn layer(&self, inner: S) -> Self::Service {
        RequestIdService { inner }
    }
}

// ── Service ───────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct RequestIdService<S> {
    inner: S,
}

impl<S> Service<Request<Body>> for RequestIdService<S>
where
    S: Service<Request<Body>, Response = Response<Body>> + Clone + Send + 'static,
    S::Future: Send + 'static,
{
    type Response = Response<Body>;
    type Error = S::Error;
    type Future = BoxFuture<'static, Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, req: Request<Body>) -> Self::Future {
        let rid = extract_or_generate_request_id(req.headers());
        let method = req.method().to_string();
        let path = req.uri().path().to_string();

        let mut inner = self.inner.clone();

        Box::pin(async move {
            let span = tracing::info_span!(
                "http_request",
                request_id = %rid,
                method = %method,
                path = %path,
            );

            let fut = {
                use tracing::Instrument;
                inner.call(req).instrument(span)
            };

            let mut resp = fut.await?;

            // Echo the request-id back so callers can correlate logs
            if let Ok(hv) = HeaderValue::from_str(&rid) {
                resp.headers_mut().insert("x-request-id", hv);
            }

            Ok(resp)
        })
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Extract a valid 12-char lowercase hex `X-Request-ID`, or generate one.
fn extract_or_generate_request_id(headers: &HeaderMap) -> String {
    if let Some(hv) = headers.get("x-request-id") {
        if let Ok(s) = hv.to_str() {
            let s = s.trim();
            if s.len() == 12 && s.chars().all(|c| c.is_ascii_hexdigit()) {
                return s.to_lowercase();
            }
        }
    }
    // Generate: UUID v4 → strip dashes → take first 12 hex chars
    let id = Uuid::new_v4().simple().to_string();
    id[..12].to_string()
}
