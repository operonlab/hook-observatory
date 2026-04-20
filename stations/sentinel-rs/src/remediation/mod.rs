pub mod ai_repair;
pub mod frontend;
pub mod simple_restart;

use crate::checker;
use crate::checker::registry::CHECKS;
use crate::config::Config;
use crate::models::now_epoch;
use crate::{notify, push};
use crate::state::InterventionEngine;
use ai_repair::{AiRepairEngine, CompletionStatus, Outcome};
use serde_json::json;
use sqlx::SqlitePool;
use std::sync::Arc;
use uuid::Uuid;

pub struct Remediator {
    http: reqwest::Client,
    engine: Arc<InterventionEngine>,
    pool: SqlitePool,
    cfg: Arc<Config>,
    pub ai: AiRepairEngine,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RepairOutcome {
    Healed,
    Escalated,
    Dispatched,
}

impl Remediator {
    pub fn new(engine: Arc<InterventionEngine>, pool: SqlitePool, cfg: Arc<Config>) -> Self {
        Self {
            http: checker::build_http_client(),
            engine,
            pool,
            cfg,
            ai: AiRepairEngine::new(),
        }
    }

    async fn send_notifications(&self, service: &str, event: &str, success: bool) {
        let payload = json!({
            "service": service,
            "event": event,
            "success": success,
            "timestamp": now_epoch(),
        });
        push::publish(&self.cfg.redis_url, &self.cfg.redis_push_channel, &payload).await;
        notify::broadcast_webhooks(&self.pool, event, &payload).await;
        let (title, body) = if success {
            (
                format!("Sentinel: {} recovered", service),
                format!("Auto-remediation succeeded via {}", event),
            )
        } else {
            (
                format!("Sentinel: {} ESCALATED", service),
                format!("Auto-remediation failed at {}, manual intervention needed", event),
            )
        };
        notify::macos_notify(&title, &body).await;
    }

    /// Attempt Layer 1 → 2 → 3 in order. Returns the final outcome.
    pub async fn dispatch(&self, service: &str) -> RepairOutcome {
        let incident_id = self.create_incident(service).await.ok();
        tracing::warn!(service, "remediation dispatch");
        self.engine.mark_notified(service);

        // ── Layer 1 ─────────────────────────────────
        if simple_restart::can_restart(service) {
            self.update_incident_status(incident_id.as_deref(), "identified", None).await.ok();
            match simple_restart::restart(service).await {
                Ok(()) => {
                    if self.verify_recovered(service).await {
                        self.resolve_incident(incident_id.as_deref(), "layer1_simple_restart", true).await.ok();
                        self.send_notifications(service, "layer1_simple_restart", true).await;
                        return RepairOutcome::Healed;
                    }
                }
                Err(e) => tracing::warn!(service, "layer1 failed: {}", e),
            }
        }

        // ── Layer 2 ─────────────────────────────────
        if frontend::applicable(service) {
            match frontend::rebuild().await {
                Ok(()) => {
                    if self.verify_recovered(service).await {
                        self.resolve_incident(incident_id.as_deref(), "layer2_frontend_rebuild", true).await.ok();
                        self.send_notifications(service, "layer2_frontend_rebuild", true).await;
                        return RepairOutcome::Healed;
                    }
                }
                Err(e) => tracing::warn!(service, "layer2 failed: {}", e),
            }
        }

        // ── Layer 3 ─────────────────────────────────
        let detail = format!("service {} failed light check", service);
        match self.ai.dispatch(service, &detail).await {
            Outcome::Dispatched(pane) => {
                self.engine.set_repairing(service, Some(pane));
                self.engine.set_incident_id(service, incident_id.clone());
                self.update_incident_status(incident_id.as_deref(), "repairing", None).await.ok();
                RepairOutcome::Dispatched
            }
            Outcome::PaneUnavailable | Outcome::Disabled => {
                self.resolve_incident(incident_id.as_deref(), "layer3_unavailable", false).await.ok();
                self.engine.set_repair_done(service, false);
                self.send_notifications(service, "layer3_unavailable", false).await;
                RepairOutcome::Escalated
            }
        }
    }

    /// Called by repair_loop each tick to resolve REPAIRING services.
    pub async fn check_pending_repairs(&self) {
        for svc in self.ai.active_services() {
            match self.ai.check_completion(&svc) {
                Some(CompletionStatus::Success) => {
                    let incident_id = self.engine.get_or_create(&svc).incident_id;
                    self.engine.set_repair_done(&svc, true);
                    self.resolve_incident(incident_id.as_deref(), "layer3_ai_repair", true).await.ok();
                    self.send_notifications(&svc, "layer3_ai_repair", true).await;
                }
                Some(CompletionStatus::Failure) | Some(CompletionStatus::Timeout) => {
                    let incident_id = self.engine.get_or_create(&svc).incident_id;
                    self.engine.set_repair_done(&svc, false);
                    self.resolve_incident(incident_id.as_deref(), "layer3_ai_repair", false).await.ok();
                    self.send_notifications(&svc, "layer3_ai_repair", false).await;
                }
                Some(CompletionStatus::Running) | None => { /* keep */ }
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

    async fn update_incident_status(
        &self,
        id: Option<&str>,
        status: &str,
        diagnosis: Option<String>,
    ) -> anyhow::Result<()> {
        let Some(id) = id else { return Ok(()); };
        sqlx::query(
            "UPDATE incidents SET status = ?, diagnosis = COALESCE(?, diagnosis) WHERE id = ?",
        )
        .bind(status)
        .bind(diagnosis)
        .bind(id)
        .execute(&self.pool)
        .await?;
        Ok(())
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
