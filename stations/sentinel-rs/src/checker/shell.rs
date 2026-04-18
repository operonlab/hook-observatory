use super::registry::Check;
use crate::models::{CheckResult, CheckStatus};
use std::time::{Duration, Instant};
use tokio::process::Command;
use tokio::time::timeout;

pub async fn run(check: &Check) -> CheckResult {
    let start = Instant::now();
    let mut cmd = Command::new("/bin/sh");
    cmd.arg("-c").arg(check.target);
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());

    let result = timeout(Duration::from_secs(check.timeout_sec), cmd.output()).await;
    let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;

    match result {
        Ok(Ok(out)) => {
            let stdout = String::from_utf8_lossy(&out.stdout).to_string();
            let success = out.status.success();

            if !success {
                let stderr = String::from_utf8_lossy(&out.stderr).to_string();
                return CheckResult {
                    service: check.name.to_string(),
                    status: if check.optional {
                        CheckStatus::Skipped
                    } else {
                        CheckStatus::Unhealthy
                    },
                    response_ms: elapsed_ms,
                    detail: Some(format!("exit {:?}: {}", out.status.code(), stderr.trim())),
                };
            }

            if let Some(needle) = check.expect_contains {
                if !stdout.contains(needle) {
                    return CheckResult {
                        service: check.name.to_string(),
                        status: CheckStatus::Unhealthy,
                        response_ms: elapsed_ms,
                        detail: Some(format!("missing '{}' in stdout", needle)),
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
        Ok(Err(e)) => CheckResult {
            service: check.name.to_string(),
            status: CheckStatus::Unhealthy,
            response_ms: elapsed_ms,
            detail: Some(format!("spawn error: {}", e)),
        },
        Err(_) => CheckResult {
            service: check.name.to_string(),
            status: CheckStatus::Timeout,
            response_ms: elapsed_ms,
            detail: Some(format!("timeout after {}s", check.timeout_sec)),
        },
    }
}
