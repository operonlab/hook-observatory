use crate::state::AppState;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub async fn run(state: AppState) {
    let interval = Duration::from_secs(state.cfg.health_interval);
    let health_url = format!("{}/health", state.cfg.remote_url);
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .expect("failed to build health check client");
    loop {
        let result = http.get(&health_url).send().await;
        let mut guard = state.health.write().await;
        guard.last_check = unix_now();
        match result {
            Ok(resp) if resp.status().is_success() => {
                guard.healthy = true;
                guard.last_error = String::new();
            }
            Ok(resp) => {
                guard.healthy = false;
                guard.last_error = format!("HTTP {}", resp.status().as_u16());
                tracing::warn!(status = %resp.status(), "remote health check non-2xx");
            }
            Err(e) => {
                guard.healthy = false;
                guard.last_error = e.to_string();
                tracing::warn!(error = %e, "remote health check failed");
            }
        }
        drop(guard);
        tokio::time::sleep(interval).await;
    }
}

fn unix_now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}
