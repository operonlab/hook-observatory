use crate::config::Config;
use crate::models::{now_epoch, CheckStatus, ServiceTracker, State};
use dashmap::DashMap;
use std::path::PathBuf;
use std::sync::Arc;

pub struct InterventionEngine {
    trackers: DashMap<String, ServiceTracker>,
    cfg: Arc<Config>,
}

impl InterventionEngine {
    pub fn new(cfg: Arc<Config>) -> Self {
        Self { trackers: DashMap::new(), cfg }
    }

    fn lock_path(&self, service: &str) -> PathBuf {
        self.cfg.lock_dir.join(format!("{}.lock", service))
    }

    pub fn get_or_create(&self, service: &str) -> ServiceTracker {
        self.trackers
            .entry(service.to_string())
            .or_insert_with(|| ServiceTracker::new(service))
            .clone()
    }

    pub fn all(&self) -> Vec<ServiceTracker> {
        self.trackers.iter().map(|e| e.value().clone()).collect()
    }

    pub fn update_light(&self, service: &str, status: CheckStatus, response_ms: f64) {
        let mut tracker = self
            .trackers
            .entry(service.to_string())
            .or_insert_with(|| ServiceTracker::new(service));

        tracker.light_status = Some(status);
        tracker.last_light_check = now_epoch();
        tracker.response_ms = response_ms;
        self.evaluate(&mut tracker);
    }

    fn evaluate(&self, tracker: &mut ServiceTracker) {
        let now = now_epoch();
        let intervention_delay = self.cfg.check_intervention_delay_sec as f64;
        let repair_timeout = self.cfg.check_repair_timeout_sec as f64;

        let is_ok = tracker.light_status.map(|s| s.is_ok()).unwrap_or(false);

        match tracker.state {
            State::Healthy => {
                if !is_ok && tracker.light_status.is_some() {
                    tracker.state = State::Observing;
                    tracker.first_failure_at = now;
                }
            }
            State::Observing => {
                if is_ok {
                    tracker.state = State::Healthy;
                    tracker.first_failure_at = 0.0;
                } else if tracker.first_failure_at > 0.0
                    && (now - tracker.first_failure_at) >= intervention_delay
                {
                    tracker.state = State::Intervening;
                }
            }
            State::Intervening => {
                if is_ok {
                    tracker.state = State::Healthy;
                    tracker.first_failure_at = 0.0;
                }
            }
            State::Repairing => {
                if tracker.repair_started_at > 0.0
                    && (now - tracker.repair_started_at) >= repair_timeout
                {
                    tracker.state = State::Escalated;
                }
                if is_ok {
                    tracker.state = State::Healthy;
                    tracker.first_failure_at = 0.0;
                    tracker.repair_started_at = 0.0;
                    tracker.repair_pane = None;
                }
            }
            State::Escalated => {
                if is_ok {
                    tracker.state = State::Healthy;
                    tracker.first_failure_at = 0.0;
                }
            }
            State::Maintenance => {
                if !self.has_active_lock(&tracker.service) {
                    tracker.state = State::Healthy;
                    tracker.agent_id = None;
                    tracker.agent_pid = None;
                }
            }
        }
    }

    pub fn should_intervene(&self, service: &str) -> bool {
        self.trackers
            .get(service)
            .map(|t| t.state == State::Intervening)
            .unwrap_or(false)
    }

    pub fn set_repairing(&self, service: &str, pane: Option<String>) {
        if let Some(mut t) = self.trackers.get_mut(service) {
            t.state = State::Repairing;
            t.repair_pane = pane;
            t.repair_started_at = now_epoch();
        }
    }

    pub fn set_repair_done(&self, service: &str, success: bool) {
        if let Some(mut t) = self.trackers.get_mut(service) {
            t.state = if success { State::Healthy } else { State::Escalated };
            t.repair_pane = None;
            t.repair_started_at = 0.0;
            t.incident_id = None;
            if success {
                t.first_failure_at = 0.0;
            }
        }
    }

    pub fn mark_notified(&self, service: &str) {
        if let Some(mut t) = self.trackers.get_mut(service) {
            t.last_notified_at = now_epoch();
        }
    }

    pub fn set_incident_id(&self, service: &str, id: Option<String>) {
        if let Some(mut t) = self.trackers.get_mut(service) {
            t.incident_id = id;
        }
    }

    pub fn notify_agent(
        &self,
        service: &str,
        agent_id: String,
        pid: Option<i32>,
        estimated_duration: u64,
    ) -> anyhow::Result<()> {
        let lock_path = self.lock_path(service);
        if let Some(parent) = lock_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(
            &lock_path,
            format!("{}\n{}\n{}\n", agent_id, estimated_duration, now_epoch()),
        )?;

        let mut tracker = self
            .trackers
            .entry(service.to_string())
            .or_insert_with(|| ServiceTracker::new(service));
        tracker.agent_id = Some(agent_id);
        tracker.agent_pid = pid;
        tracker.agent_notified_at = now_epoch();
        if matches!(tracker.state, State::Healthy | State::Observing) {
            tracker.state = State::Maintenance;
        }
        Ok(())
    }

    pub fn resolve_agent(&self, service: &str, agent_id: &str) -> anyhow::Result<()> {
        let lock_path = self.lock_path(service);
        let _ = std::fs::remove_file(&lock_path);

        if let Some(mut t) = self.trackers.get_mut(service) {
            if t.agent_id.as_deref() == Some(agent_id) {
                t.agent_id = None;
                t.agent_pid = None;
                t.agent_notified_at = 0.0;
                if t.state == State::Maintenance {
                    t.state = State::Healthy;
                }
            }
        }
        Ok(())
    }

    fn has_active_lock(&self, service: &str) -> bool {
        let path = self.lock_path(service);
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => return false,
        };
        let lines: Vec<&str> = content.lines().collect();
        if lines.len() < 3 {
            return false;
        }
        let estimated: f64 = lines[1].parse().unwrap_or(300.0);
        let created: f64 = lines[2].parse().unwrap_or(0.0);
        let ttl = estimated + 300.0;
        let is_active = (now_epoch() - created) < ttl;
        if !is_active {
            let _ = std::fs::remove_file(&path);
        }
        is_active
    }

    pub fn sweep_expired_locks(&self) {
        let services: Vec<String> = self
            .trackers
            .iter()
            .filter(|e| e.value().state == State::Maintenance)
            .map(|e| e.key().clone())
            .collect();
        for svc in services {
            if !self.has_active_lock(&svc) {
                if let Some(mut t) = self.trackers.get_mut(&svc) {
                    t.state = State::Healthy;
                    t.agent_id = None;
                    t.agent_pid = None;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_cfg() -> Arc<Config> {
        Arc::new(Config {
            port: 4102,
            host: "127.0.0.1".into(),
            database_path: "/tmp/sentinel-test.db".into(),
            redis_url: "redis://127.0.0.1:6379".into(),
            redis_push_channel: "workshop:push".into(),
            lock_dir: std::env::temp_dir().join("sentinel-test-locks"),
            log_dir: std::env::temp_dir().join("sentinel-test-logs"),
            check_light_interval_sec: 30,
            check_intervention_delay_sec: 300,
            check_repair_timeout_sec: 600,
            repair_monitor_interval_sec: 15,
            purge_interval_sec: 21600,
            purge_retention_days: 30,
            notification_cooldown_sec: 1800,
            sysmon_url: "http://127.0.0.1:10102".into(),
        })
    }

    #[test]
    fn healthy_to_observing_on_unhealthy() {
        let engine = InterventionEngine::new(test_cfg());
        engine.update_light("svc", CheckStatus::Unhealthy, 0.0);
        let t = engine.get_or_create("svc");
        assert_eq!(t.state, State::Observing);
        assert!(t.first_failure_at > 0.0);
    }

    #[test]
    fn observing_back_to_healthy_on_recovery() {
        let engine = InterventionEngine::new(test_cfg());
        engine.update_light("svc", CheckStatus::Unhealthy, 0.0);
        engine.update_light("svc", CheckStatus::Healthy, 0.0);
        let t = engine.get_or_create("svc");
        assert_eq!(t.state, State::Healthy);
    }

    #[test]
    fn skipped_treated_as_ok() {
        let engine = InterventionEngine::new(test_cfg());
        engine.update_light("svc", CheckStatus::Skipped, 0.0);
        let t = engine.get_or_create("svc");
        assert_eq!(t.state, State::Healthy);
    }
}
