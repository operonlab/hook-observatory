//! In-memory session store — port of `agent_metrics.session_store`.
//!
//! Async-safe via `tokio::sync::Mutex`. The web ingest handler writes here;
//! the aggregator task drains snapshots into SQLite.

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;
use uuid::Uuid;

const SESSION_EXPIRY_SECONDS: f64 = 7200.0;
const SESSION_REMOVE_AGE_SECONDS: f64 = 86400.0;

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ContextInfo {
    #[serde(default)]
    pub input_tokens: i64,
    #[serde(default)]
    pub output_tokens: i64,
    #[serde(default)]
    pub cache_creation_tokens: i64,
    #[serde(default)]
    pub cache_read_tokens: i64,
    #[serde(default)]
    pub window_size: i64,
    #[serde(default)]
    pub used_pct: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct IngestRequest {
    pub sid: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default = "default_cli")]
    pub cli: String,
    #[serde(default)]
    pub cost: f64,
    #[serde(default)]
    pub model_id: String,
    #[serde(default)]
    pub model_display: String,
    #[serde(default)]
    pub project: String,
    #[serde(default)]
    pub context: ContextInfo,
}

fn default_cli() -> String {
    "claude".into()
}

#[derive(Debug, Clone, Serialize)]
pub struct IngestResponse {
    pub total: f64,
    pub sessions: usize,
    pub daily: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SessionInfo {
    pub id: String,
    pub sid: String,
    pub cli: String,
    pub model_id: String,
    pub model_display: String,
    pub project: String,
    pub cost_usd: f64,
    pub context_used_pct: f64,
    pub context_window_size: i64,
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub cache_creation_tokens: i64,
    pub cache_read_tokens: i64,
    pub first_seen: String,
    pub last_seen: String,
    pub is_active: bool,
    #[serde(skip)]
    pub last_seen_ts: f64,
}

#[derive(Debug, Default)]
pub struct SessionStoreInner {
    pub sessions: BTreeMap<String, SessionInfo>,
    pub daily_cost: f64,
    pub current_date: String,
}

#[derive(Clone, Default)]
pub struct SessionStore {
    pub inner: Arc<Mutex<SessionStoreInner>>,
}

fn today() -> String {
    Utc::now().format("%Y-%m-%d").to_string()
}

fn now_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

fn round4(v: f64) -> f64 {
    (v * 10_000.0).round() / 10_000.0
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

impl SessionStore {
    pub async fn ingest(&self, req: IngestRequest) -> IngestResponse {
        let now_iso = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
        let now_ts_v = now_ts();
        let mut inner = self.inner.lock().await;

        let today_v = today();
        if inner.current_date != today_v {
            inner.current_date = today_v.clone();
            inner.daily_cost = 0.0;
            for s in inner.sessions.values_mut() {
                s.is_active = false;
            }
            inner.sessions.clear();
        }

        let key = if !req.session_id.is_empty() {
            req.session_id.clone()
        } else {
            req.sid.clone()
        };
        let old_cost = inner.sessions.get(&key).map(|s| s.cost_usd).unwrap_or(0.0);
        inner.daily_cost = round4(inner.daily_cost - old_cost + req.cost);

        let entry = inner.sessions.entry(key.clone()).or_insert_with(|| SessionInfo {
            id: if req.session_id.is_empty() {
                Uuid::new_v4().simple().to_string()
            } else {
                req.session_id.clone()
            },
            sid: req.sid.clone(),
            cli: req.cli.clone(),
            model_id: String::new(),
            model_display: String::new(),
            project: String::new(),
            cost_usd: 0.0,
            context_used_pct: 0.0,
            context_window_size: 0,
            input_tokens: 0,
            output_tokens: 0,
            cache_creation_tokens: 0,
            cache_read_tokens: 0,
            first_seen: now_iso.clone(),
            last_seen: now_iso.clone(),
            is_active: true,
            last_seen_ts: now_ts_v,
        });

        entry.cli = if req.cli.is_empty() { entry.cli.clone() } else { req.cli };
        if !req.model_id.is_empty() {
            entry.model_id = req.model_id;
        }
        if !req.model_display.is_empty() {
            entry.model_display = req.model_display;
        }
        if !req.project.is_empty() {
            entry.project = req.project;
        }
        entry.cost_usd = req.cost;
        entry.context_used_pct = req.context.used_pct;
        entry.context_window_size = req.context.window_size;
        entry.input_tokens = req.context.input_tokens;
        entry.output_tokens = req.context.output_tokens;
        entry.cache_creation_tokens = req.context.cache_creation_tokens;
        entry.cache_read_tokens = req.context.cache_read_tokens;
        entry.last_seen = now_iso;
        entry.last_seen_ts = now_ts_v;
        entry.is_active = true;

        let now_ts_for_stale = now_ts_v;
        let mut total = 0.0;
        let mut count = 0_usize;
        for s in inner.sessions.values() {
            if now_ts_for_stale - s.last_seen_ts > SESSION_EXPIRY_SECONDS {
                continue;
            }
            total += s.cost_usd;
            count += 1;
        }
        IngestResponse {
            total: round4(total),
            sessions: count,
            daily: round4(inner.daily_cost),
        }
    }

    pub async fn get_active_sessions(&self) -> Vec<SessionInfo> {
        let inner = self.inner.lock().await;
        let now = now_ts();
        inner
            .sessions
            .values()
            .filter(|s| now - s.last_seen_ts <= SESSION_EXPIRY_SECONDS)
            .cloned()
            .collect()
    }

    pub async fn get_snapshot(&self) -> serde_json::Value {
        let inner = self.inner.lock().await;
        let now = now_ts();
        let active: Vec<&SessionInfo> = inner
            .sessions
            .values()
            .filter(|s| now - s.last_seen_ts <= SESSION_EXPIRY_SECONDS)
            .collect();
        serde_json::json!({
            "date": if inner.current_date.is_empty() { today() } else { inner.current_date.clone() },
            "total_cost_usd": round4(inner.daily_cost),
            "active_sessions": active.len(),
            "sessions": active,
        })
    }

    pub async fn collect_pending_snapshots(&self) -> Vec<SnapshotRow> {
        let inner = self.inner.lock().await;
        let now_iso = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
        let now = now_ts();
        let mut out = Vec::new();
        for s in inner.sessions.values() {
            if now - s.last_seen_ts > SESSION_EXPIRY_SECONDS {
                continue;
            }
            out.push(SnapshotRow {
                id: Uuid::new_v4().simple().to_string(),
                ts: now_iso.clone(),
                session_id: s.id.clone(),
                sid: s.sid.clone(),
                cli: s.cli.clone(),
                cost_usd: s.cost_usd,
                context_used_pct: s.context_used_pct,
                input_tokens: s.input_tokens,
                output_tokens: s.output_tokens,
            });
        }
        out
    }

    pub async fn expire_stale(&self) -> usize {
        let mut inner = self.inner.lock().await;
        let now = now_ts();
        let mut expired = 0;
        let stale_keys: Vec<String> = inner
            .sessions
            .iter()
            .filter(|(_, s)| now - s.last_seen_ts > SESSION_EXPIRY_SECONDS)
            .map(|(k, _)| k.clone())
            .collect();
        for k in stale_keys {
            if let Some(s) = inner.sessions.get_mut(&k) {
                s.is_active = false;
                expired += 1;
            }
        }
        let day_ago = now - SESSION_REMOVE_AGE_SECONDS;
        let remove_keys: Vec<String> = inner
            .sessions
            .iter()
            .filter(|(_, s)| s.last_seen_ts < day_ago)
            .map(|(k, _)| k.clone())
            .collect();
        for k in remove_keys {
            inner.sessions.remove(&k);
        }
        expired
    }

    pub async fn maybe_daily_rollover(&self) -> Option<DailySummaryRow> {
        let mut inner = self.inner.lock().await;
        let today_v = today();
        if inner.current_date.is_empty() || inner.current_date == today_v {
            return None;
        }
        let now = now_ts();
        let all: Vec<SessionInfo> = inner.sessions.values().cloned().collect();
        let total_input: i64 = all.iter().map(|s| s.input_tokens).sum();
        let total_output: i64 = all.iter().map(|s| s.output_tokens).sum();
        let ctx_pcts: Vec<f64> = all
            .iter()
            .filter(|s| s.context_used_pct > 0.0)
            .map(|s| s.context_used_pct)
            .collect();
        let avg_ctx = if ctx_pcts.is_empty() {
            0.0
        } else {
            round1(ctx_pcts.iter().sum::<f64>() / ctx_pcts.len() as f64)
        };
        let max_ctx = if ctx_pcts.is_empty() {
            0.0
        } else {
            round1(ctx_pcts.iter().cloned().fold(0.0, f64::max))
        };
        let active_count = all
            .iter()
            .filter(|s| now - s.last_seen_ts <= SESSION_EXPIRY_SECONDS)
            .count();
        let summary = DailySummaryRow {
            id: Uuid::new_v4().simple().to_string(),
            date: inner.current_date.clone(),
            total_cost_usd: round4(inner.daily_cost),
            total_sessions: all.len() as i64,
            peak_concurrent: active_count as i64,
            total_input_tokens: total_input,
            total_output_tokens: total_output,
            avg_context_pct: avg_ctx,
            max_context_pct: max_ctx,
        };
        inner.current_date = today_v;
        inner.daily_cost = 0.0;
        inner.sessions.clear();
        Some(summary)
    }
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct SnapshotRow {
    pub id: String,
    pub ts: String,
    pub session_id: String,
    pub sid: String,
    pub cli: String,
    pub cost_usd: f64,
    pub context_used_pct: f64,
    pub input_tokens: i64,
    pub output_tokens: i64,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct DailySummaryRow {
    pub id: String,
    pub date: String,
    pub total_cost_usd: f64,
    pub total_sessions: i64,
    pub peak_concurrent: i64,
    pub total_input_tokens: i64,
    pub total_output_tokens: i64,
    pub avg_context_pct: f64,
    pub max_context_pct: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn req(sid: &str, cost: f64) -> IngestRequest {
        IngestRequest {
            sid: sid.into(),
            session_id: String::new(),
            cli: "claude".into(),
            cost,
            model_id: String::new(),
            model_display: String::new(),
            project: String::new(),
            context: ContextInfo::default(),
        }
    }

    #[tokio::test]
    async fn ingest_creates_session_and_aggregates() {
        let store = SessionStore::default();
        let r1 = store.ingest(req("aaaa", 0.5)).await;
        assert_eq!(r1.sessions, 1);
        assert!((r1.total - 0.5).abs() < 1e-6);
        assert!((r1.daily - 0.5).abs() < 1e-6);

        let r2 = store.ingest(req("bbbb", 1.25)).await;
        assert_eq!(r2.sessions, 2);
        assert!((r2.total - 1.75).abs() < 1e-6);
        assert!((r2.daily - 1.75).abs() < 1e-6);

        // Re-ingest first session at higher cost — daily should reflect delta only
        let r3 = store.ingest(req("aaaa", 2.0)).await;
        assert_eq!(r3.sessions, 2);
        assert!((r3.total - 3.25).abs() < 1e-6, "total={}", r3.total);
        assert!((r3.daily - 3.25).abs() < 1e-6, "daily={}", r3.daily);
    }

    #[tokio::test]
    async fn collect_pending_yields_one_per_active_session() {
        let store = SessionStore::default();
        store.ingest(req("xxxx", 0.1)).await;
        store.ingest(req("yyyy", 0.2)).await;
        let snaps = store.collect_pending_snapshots().await;
        assert_eq!(snaps.len(), 2);
        assert!(snaps.iter().any(|s| s.sid == "xxxx"));
        assert!(snaps.iter().any(|s| s.sid == "yyyy"));
    }
}
