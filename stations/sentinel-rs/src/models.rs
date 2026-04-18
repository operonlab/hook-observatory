use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    Healthy,
    Observing,
    Intervening,
    Repairing,
    Escalated,
    Maintenance,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CheckStatus {
    Healthy,
    Unhealthy,
    Timeout,
    Degraded,
    Skipped,
    Operational,
    MajorOutage,
}

impl CheckStatus {
    pub fn is_ok(self) -> bool {
        matches!(self, CheckStatus::Healthy | CheckStatus::Operational | CheckStatus::Skipped)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceTracker {
    pub service: String,
    pub state: State,
    pub light_status: Option<CheckStatus>,
    pub deep_status: Option<CheckStatus>,
    pub last_light_check: f64,
    pub last_deep_check: f64,
    pub first_failure_at: f64,
    pub agent_id: Option<String>,
    pub agent_notified_at: f64,
    pub agent_pid: Option<i32>,
    pub repair_pane: Option<String>,
    pub repair_started_at: f64,
    pub incident_id: Option<String>,
    pub response_ms: f64,
    pub last_notified_at: f64,
}

impl ServiceTracker {
    pub fn new(service: impl Into<String>) -> Self {
        Self {
            service: service.into(),
            state: State::Healthy,
            light_status: None,
            deep_status: None,
            last_light_check: 0.0,
            last_deep_check: 0.0,
            first_failure_at: 0.0,
            agent_id: None,
            agent_notified_at: 0.0,
            agent_pid: None,
            repair_pane: None,
            repair_started_at: 0.0,
            incident_id: None,
            response_ms: 0.0,
            last_notified_at: 0.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckResult {
    pub service: String,
    pub status: CheckStatus,
    pub response_ms: f64,
    pub detail: Option<String>,
}

pub fn now_epoch() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}
