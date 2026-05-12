//! OCR client — delegates to stations/ocr service (port 10202, Apple Vision Swift binary).
//!
//! GET `{base_url}/extract?engine=apple&languages=zh-Hant,zh-Hans,en&path={absolute_path}`
//! Response: `{"text": "...", "engine": "apple", "lines": [...]}`
//!           or `{"error": "..."}`

use anyhow::{anyhow, Result};
use serde::Deserialize;
use std::path::Path;

#[derive(Debug, Deserialize)]
struct OcrSuccess {
    text: String,
    // engine and lines are present but we only need text
}

#[derive(Debug, Deserialize)]
struct OcrError {
    error: String,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum OcrResponse {
    Success(OcrSuccess),
    Err(OcrError),
}

/// Call the OCR service with the default engine (apple / Swift Vision).
///
/// `languages` controls the Vision recognition hints, e.g. `&["zh-Hant", "zh-Hans", "en"]`.
/// An empty slice defaults to `zh-Hant,zh-Hans,en`.
pub async fn extract_text(
    client: &reqwest::Client,
    ocr_base_url: &str,
    image_path: &Path,
    languages: &[&str],
) -> Result<String> {
    extract_text_with_engine(client, ocr_base_url, image_path, languages, "apple").await
}

/// Same as [`extract_text`] but allows choosing the underlying engine.
/// Useful for falling back to `claude` (higher accuracy, API cost) when the
/// default apple engine produces URL slugs that fail HEAD validation.
pub async fn extract_text_with_engine(
    client: &reqwest::Client,
    ocr_base_url: &str,
    image_path: &Path,
    languages: &[&str],
    engine: &str,
) -> Result<String> {
    let abs = image_path
        .canonicalize()
        .unwrap_or_else(|_| image_path.to_path_buf());
    let path_str = abs
        .to_str()
        .ok_or_else(|| anyhow!("non-UTF-8 path: {:?}", abs))?;

    let langs = if languages.is_empty() {
        "zh-Hant,zh-Hans,en".to_string()
    } else {
        languages.join(",")
    };

    // URL-encode the path so special chars (spaces, parens, etc.) are safe.
    let encoded_path = urlencoding::encode(path_str);

    let url = format!(
        "{base}/extract?engine={engine}&languages={langs}&path={path}",
        base = ocr_base_url.trim_end_matches('/'),
        engine = engine,
        langs = langs,
        path = encoded_path,
    );

    tracing::debug!("OCR request: {}", url);

    // ocr station's /extract is POST (all query params, no body)
    let resp = client
        .post(&url)
        .send()
        .await
        .map_err(|e| anyhow!("OCR HTTP error: {}", e))?;

    let status = resp.status();
    let body = resp
        .text()
        .await
        .map_err(|e| anyhow!("OCR read body error: {}", e))?;

    if !status.is_success() {
        return Err(anyhow!("OCR service returned HTTP {}: {}", status, body));
    }

    let parsed: OcrResponse = serde_json::from_str(&body)
        .map_err(|e| anyhow!("OCR JSON parse error: {} — body: {}", e, &body[..body.len().min(200)]))?;

    match parsed {
        OcrResponse::Success(s) => Ok(s.text),
        OcrResponse::Err(e) => Err(anyhow!("OCR service error: {}", e.error)),
    }
}
