use super::registry::Check;
use crate::models::{CheckResult, CheckStatus};
use std::time::{Duration, Instant};

pub async fn run(client: &reqwest::Client, check: &Check) -> CheckResult {
    let start = Instant::now();
    let req = client
        .get(check.target)
        .timeout(Duration::from_secs(check.timeout_sec));

    match req.send().await {
        Ok(resp) => {
            let status_code = resp.status();
            let body = resp.text().await.unwrap_or_default();
            let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;

            if !status_code.is_success() && status_code.as_u16() >= 500 {
                return CheckResult {
                    service: check.name.to_string(),
                    status: CheckStatus::Unhealthy,
                    response_ms: elapsed_ms,
                    detail: Some(format!("HTTP {}", status_code)),
                };
            }

            if let Some(needle) = check.expect_contains {
                if !body.contains(needle) {
                    return CheckResult {
                        service: check.name.to_string(),
                        status: CheckStatus::Unhealthy,
                        response_ms: elapsed_ms,
                        detail: Some(format!("missing '{}'", needle)),
                    };
                }
            }

            if let Some(expect_json_str) = check.expect_json {
                let want: serde_json::Value = serde_json::from_str(expect_json_str)
                    .unwrap_or(serde_json::Value::Null);
                let got: serde_json::Value = serde_json::from_str(&body)
                    .unwrap_or(serde_json::Value::Null);
                if !json_subset(&want, &got) {
                    return CheckResult {
                        service: check.name.to_string(),
                        status: CheckStatus::Unhealthy,
                        response_ms: elapsed_ms,
                        detail: Some(format!("json mismatch: want {}", expect_json_str)),
                    };
                }
            }

            CheckResult {
                service: check.name.to_string(),
                status: CheckStatus::Healthy,
                response_ms: elapsed_ms,
                detail: None,
            }
        }
        Err(err) => {
            let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
            let status = if err.is_timeout() {
                CheckStatus::Timeout
            } else if check.optional && err.is_connect() {
                CheckStatus::Skipped
            } else {
                CheckStatus::Unhealthy
            };
            CheckResult {
                service: check.name.to_string(),
                status,
                response_ms: elapsed_ms,
                detail: Some(err.to_string()),
            }
        }
    }
}

fn json_subset(want: &serde_json::Value, got: &serde_json::Value) -> bool {
    match (want, got) {
        (serde_json::Value::Object(w), serde_json::Value::Object(g)) => {
            w.iter().all(|(k, v)| g.get(k).map(|gv| json_subset(v, gv)).unwrap_or(false))
        }
        (a, b) => a == b,
    }
}
