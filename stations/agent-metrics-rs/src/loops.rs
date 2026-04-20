//! Background loops driver — sysmon tick + guardian + sweep.
//!
//! Mirrors `sysmon_loop` in Python:
//!   - every `interval` seconds, collect a snapshot
//!   - write to atomic file (FALLBACK_PATH / SYSMON_OUTPUT_PATH)
//!   - push to in-memory ring buffer for /sysmon/history (Phase 4)
//!   - per-tick guardian invocation
//!   - per-N-ticks sweep invocation
//!
//! Quota merge happens inline; SSE broadcast emits `system` and `quota`
//! events when an `EventBus` is wired into `LoopState`.

use crate::config::Settings;
use crate::guardian::{maybe_run_guardian, GuardianConfig};
use crate::sweep::{maybe_run_sweep, SweepConfig};
use crate::sysmon::{collect_all, SysmonSnapshot};
use crate::web::sse::EventBus;
use anyhow::Result;
use sqlx::SqlitePool;
use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Clone)]
pub struct LoopState {
    pub latest: Arc<RwLock<Option<SysmonSnapshot>>>,
    pub history: Arc<RwLock<VecDeque<SysmonSnapshot>>>,
    pub history_size: usize,
    pub event_bus: Option<EventBus>,
}

impl LoopState {
    pub fn new(history_size: usize) -> Self {
        Self {
            latest: Arc::new(RwLock::new(None)),
            history: Arc::new(RwLock::new(VecDeque::with_capacity(history_size))),
            history_size,
            event_bus: None,
        }
    }

    pub fn with_event_bus(mut self, bus: EventBus) -> Self {
        self.event_bus = Some(bus);
        self
    }
}

pub async fn sysmon_tick(
    state: &LoopState,
    settings: &Settings,
    pool: &SqlitePool,
    guardian_cfg: &GuardianConfig,
    sweep_cfg: &SweepConfig,
    tick: u64,
) -> Result<SysmonSnapshot> {
    let mut snap = collect_all().await;

    // Merge Redis-cached quota into the snapshot so the `llm_*` fields are
    // populated for /sysmon/current consumers and the atomic file readers
    // (tmux statusline). Best-effort: if Redis is down, leave defaults.
    let q = crate::collectors::quota::get_quota(settings).await;
    snap.llm_cc_5h = q.llm_cc_5h;
    snap.llm_cc_7d = q.llm_cc_7d;
    snap.llm_cc_ex = q.llm_cc_ex;
    snap.llm_cx_5h = q.llm_cx_5h;
    snap.llm_cx_7d = q.llm_cx_7d;
    snap.llm_gm_pro = q.llm_gm_pro;
    snap.llm_display = q.llm_display;

    {
        let mut latest = state.latest.write().await;
        *latest = Some(snap.clone());
    }
    {
        let mut hist = state.history.write().await;
        if hist.len() == state.history_size {
            hist.pop_front();
        }
        hist.push_back(snap.clone());
    }

    if let Ok(json) = serde_json::to_string(&snap) {
        atomic_write(&settings.sysmon_output_path, &json);
    }

    // SSE: push `system` snapshot every tick + `quota` event whenever any quota
    // field is non-default. Frontend uses `quota` to refresh its quota panel
    // and `system` for CPU/MEM/NET widgets.
    if let Some(bus) = state.event_bus.as_ref() {
        if let Ok(v) = serde_json::to_value(&snap) {
            bus.emit("system", v);
        }
        let q = serde_json::json!({
            "llm_cc_5h": snap.llm_cc_5h,
            "llm_cc_7d": snap.llm_cc_7d,
            "llm_cc_ex": snap.llm_cc_ex,
            "llm_cx_5h": snap.llm_cx_5h,
            "llm_cx_7d": snap.llm_cx_7d,
            "llm_gm_pro": snap.llm_gm_pro,
            "llm_display": snap.llm_display,
        });
        bus.emit("quota", q);
    }

    if let Err(e) = maybe_run_guardian(pool, guardian_cfg, snap.mem_pressure).await {
        tracing::warn!(error = %e, "guardian_tick_error");
    }

    // Match Python's pre-increment semantics: only fire sweep on tick > 0
    // (Python increments _tick_count to 1 BEFORE the first modulo check, so
    // the very first tick never triggers sweep).
    let sweep_ticks = (sweep_cfg.interval as u64).saturating_div(settings.sysmon_collect_interval);
    if sweep_ticks > 0 && tick > 0 && tick % sweep_ticks == 0 {
        if let Err(e) = maybe_run_sweep(pool, sweep_cfg).await {
            tracing::warn!(error = %e, "sweep_tick_error");
        }
    }

    Ok(snap)
}

pub async fn run_sysmon_loop(
    state: LoopState,
    settings: Settings,
    pool: SqlitePool,
) -> Result<()> {
    let guardian_cfg = GuardianConfig::default_for(&settings);
    let sweep_cfg = SweepConfig::default_for(&settings);
    let interval = std::time::Duration::from_secs(settings.sysmon_collect_interval);

    tracing::info!(
        interval_s = settings.sysmon_collect_interval,
        "sysmon_loop_started"
    );
    let mut tick: u64 = 0;
    loop {
        if let Err(e) = sysmon_tick(&state, &settings, &pool, &guardian_cfg, &sweep_cfg, tick).await {
            tracing::error!(error = %e, "sysmon_collect_error");
        }
        tick = tick.wrapping_add(1);
        tokio::time::sleep(interval).await;
    }
}

fn atomic_write(path: &str, data: &str) {
    let path_buf = std::path::Path::new(path);
    let dir = path_buf.parent().unwrap_or_else(|| std::path::Path::new("/tmp"));
    let pid = std::process::id();
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or_default();
    let tmp = dir.join(format!(".am-rs-{}-{}.tmp", pid, nanos));
    if std::fs::write(&tmp, data).is_ok() {
        if std::fs::rename(&tmp, path).is_err() {
            // rename failed (cross-device, perms, ...) — never leave the tmp behind
            let _ = std::fs::remove_file(&tmp);
        }
    } else {
        // write itself failed (e.g. dir disappeared) — best-effort cleanup in case
        let _ = std::fs::remove_file(&tmp);
    }
}
