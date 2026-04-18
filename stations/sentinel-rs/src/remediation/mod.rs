pub mod simple_restart;
pub mod frontend;
pub mod ai_repair;

use crate::checker;
use crate::checker::registry::CHECKS;
use crate::models::{CheckStatus, now_epoch};
use crate::state::InterventionEngine;
use sqlx::SqlitePool;
use std::sync::Arc;
use uuid::Uuid;

pub struct Remediator {
    http: reqwest::Client,
    engine: Arc<InterventionEngine>,
    pool: SqlitePool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RepairOutcome {
    Healed,
    Escalated,
    #[allow(dead_code)] // used when Layer 3 AI repair becomes non-stub
    Dispatched,
}

impl Remediator {
    pub fn new(engine: Arc<InterventionEngine>, pool: SqlitePool) -> Self {
        Self {
            http: checker::build_http_client(),
            engine,
            pool,
        }
    }

    /// Attempt Layer 1 → 2 → 3 in order. Returns the final outcome.
    pub async fn dispatch(&self, service: &str) -> RepairOutcome {
        let incident_id = self.create_incident(service).await.ok();
        tracing::warn!(service, "remediation dispatch");

        // ── Layer 1: SimpleRestarter ──────────────────────────
        if simple_restart::can_restart(service) {
            match simple_restart::restart(service).await {
                Ok(()) => {
                    if self.verify_recovered(service).await {
                        self.resolve_incident(incident_id.as_deref(), "layer1_simple_restart", true).await.ok();
                        return RepairOutcome::Healed;
                    }
                }
                Err(e) => tracing::warn!(service, "layer1 failed: {}", e),
            }
        }

        // ── Layer 2: FrontendRebuilder ────────────────────────
        if frontend::applicable(service) {
            match frontend::rebuild().await {
                Ok(()) => {
                    if self.verify_recovered(service).await {
                        self.resolve_incident(incident_id.as_deref(), "layer2_frontend_rebuild", true).await.ok();
                        return RepairOutcome::Healed;
                    }
                }
                Err(e) => tracing::warn!(service, "layer2 failed: {}", e),
            }
        }

        // ── Layer 3: AI repair (currently stub — returns Escalated) ──
        match ai_repair::dispatch(service).await {
            ai_repair::Outcome::Dispatched(pane) => {
                self.engine.set_repairing(service, Some(pane));
                return RepairOutcome::Dispatched;
            }
            ai_repair::Outcome::PaneUnavailable | ai_repair::Outcome::Disabled => {
                self.resolve_incident(incident_id.as_deref(), "layer3_unavailable", false).await.ok();
                self.engine.set_repair_done(service, false);
                RepairOutcome::Escalated
            }
        }
    }

    async fn verify_recovered(&self, service: &str) -> bool {
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
        if let Some(check) = CHECKS.iter().find(|c| c.name == service) {
            let result = checker::run_one(&self.http, check).await;
            if result.status.is_ok() {
                self.engine.update_light(service, result.status, result.response_ms);
                return true;
            }
        }
        false
    }

    async fn create_incident(&self, service: &str) -> anyhow::Result<String> {
        let id = Uuid::now_v7().to_string();
        sqlx::query(
            "INSERT INTO incidents (id, service, status, severity, title, detail) \
             VALUES (?, ?, 'investigating', 'major', ?, ?)",
        )
        .bind(&id)
        .bind(service)
        .bind(format!("{} unhealthy — auto-remediation started", service))
        .bind(format!(r#"{{"started_at":{}}}"#, now_epoch()))
        .execute(&self.pool)
        .await?;
        Ok(id)
    }

    async fn resolve_incident(
        &self,
        id: Option<&str>,
        layer: &str,
        success: bool,
    ) -> anyhow::Result<()> {
        let Some(id) = id else { return Ok(()); };
        let status = if success { "resolved" } else { "escalated" };
        let repair_result = format!(r#"{{"layer":"{}","success":{}}}"#, layer, success);
        sqlx::query(
            "UPDATE incidents SET status=?, repair_result=?, resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        )
        .bind(status)
        .bind(repair_result)
        .bind(id)
        .execute(&self.pool)
        .await?;
        Ok(())
    }
}
