pub mod http;
pub mod registry;
pub mod shell;

use crate::models::CheckResult;
use futures::stream::{FuturesUnordered, StreamExt};
use registry::{Check, CheckKind};
use std::time::Duration;

pub async fn run_all(client: &reqwest::Client) -> Vec<CheckResult> {
    let all_checks = registry::all_checks();
    let mut fut = FuturesUnordered::new();
    for check in all_checks {
        fut.push(run_one(client, check));
    }
    let mut results = Vec::with_capacity(all_checks.len());
    while let Some(r) = fut.next().await {
        results.push(r);
    }
    results
}

pub async fn run_one(client: &reqwest::Client, check: &Check) -> CheckResult {
    match check.kind {
        CheckKind::Http => http::run(client, check).await,
        CheckKind::Shell => shell::run(check).await,
    }
}

pub fn build_http_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .user_agent("sentinel/0.1")
        .build()
        .expect("build reqwest client")
}
