use crate::checker::{self, registry::CHECKS};
use crate::models::CheckResult;
use crate::sse::SseHub;
use crate::state::InterventionEngine;
use serde_json::json;
use sqlx::SqlitePool;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::interval;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub async fn run(
    engine: Arc<InterventionEngine>,
    pool: SqlitePool,
    sse: SseHub,
    interval_sec: u64,
    token: CancellationToken,
) {
    tokio::time::sleep(Duration::from_secs(5)).await; // warmup
    let client = checker::build_http_client();
    let mut ticker = interval(Duration::from_secs(interval_sec));

    loop {
        tokio::select! {
            _ = token.cancelled() => {
                tracing::info!("light_loop shutting down");
                return;
            }
            _ = ticker.tick() => {
                let results = checker::run_all(&client).await;
                let healthy = results.iter().filter(|r| r.status.is_ok()).count();
                tracing::info!(healthy, total = CHECKS.len(), "light check cycle");

                for r in &results {
                    engine.update_light(&r.service, r.status, r.response_ms);
                }
                if let Err(e) = persist_batch(&pool, &results).await {
                    tracing::warn!("persist_batch failed: {}", e);
                }

                engine.sweep_expired_locks();

                let payload = build_status_payload(&engine);
                sse.broadcast("status", payload);
            }
        }
    }
}

async fn persist_batch(pool: &SqlitePool, results: &[CheckResult]) -> anyhow::Result<()> {
    let mut tx = pool.begin().await?;
    for r in results {
        let id = Uuid::now_v7().to_string();
        let status = serde_json::to_string(&r.status)
            .unwrap_or_else(|_| "\"unhealthy\"".into())
            .trim_matches('"')
            .to_string();
        let detail = r.detail.as_deref().unwrap_or("");
        sqlx::query(
            "INSERT INTO health_checks (id, service, check_type, status, response_ms, detail) \
             VALUES (?, ?, 'light', ?, ?, ?)",
        )
        .bind(id)
        .bind(&r.service)
        .bind(status)
        .bind(r.response_ms)
        .bind(detail)
        .execute(&mut *tx)
        .await?;
    }
    tx.commit().await?;
    Ok(())
}

pub fn build_status_payload(engine: &InterventionEngine) -> serde_json::Value {
    let trackers = engine.all();
    let services: Vec<serde_json::Value> = trackers
        .iter()
        .map(|t| {
            let group = crate::checker::registry::CHECKS
                .iter()
                .find(|c| c.name == t.service)
                .map(|c| c.group)
                .unwrap_or("external");
            json!({
                "service": t.service,
                "state": t.state,
                "status": t.state,
                "group": group,
                "light_status": t.light_status,
                "response_ms": t.response_ms,
                "last_light_check": t.last_light_check,
                "first_failure_at": t.first_failure_at,
                "incident_id": t.incident_id,
            })
        })
        .collect();

    let total = trackers.len();
    let healthy = trackers.iter().filter(|t| t.state == crate::models::State::Healthy).count();
    let overall = if total == 0 {
        "unknown"
    } else if healthy == total {
        "operational"
    } else if healthy * 2 > total {
        "degraded"
    } else {
        "major_outage"
    };

    json!({
        "overall": overall,
        "total": total,
        "healthy": healthy,
        "services": services,
    })
}
