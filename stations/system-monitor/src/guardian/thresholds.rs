//! Pure rule engine. Mirrors `memory_guardian.py::run()` decision matrix.
//!
//! Maps a `Snapshot` to a Vec<Action>. NO side-effects — `actions.rs`
//! consumes the plan and decides whether to actually fire SIGTERM /
//! AppleScript / notifications.
//!
//! Reference (as of 2026-05-01):
//!   memory_guardian.py lines 1077-1325 — the P0–P3 ladder + presence gating.
//!   Constants below copied from the Python `DEFAULTS` dict and from
//!   user-spec'd thresholds (warn=40, crit=15).

use serde::{Deserialize, Serialize};

use super::presence::Presence;

/// Process row used by the rule engine. Aggregated from `ps -eo pid,rss,comm,cpu,age`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProcRow {
    pub pid: i32,
    pub name: String,
    pub command: String,
    pub rss_mb: u64,
    pub cpu_pct: f32,
    pub age_secs: u64,
}

/// Tick-time snapshot fed into `decide()`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub mem_level: u32,
    pub compressed_gb: f64,
    pub swap_used_gb: f64,
    pub swap_used_pct: u32,
    pub idle_seconds: i64,
    /// Top processes by RSS (already filtered by collector). Used as the
    /// haystack for P0/P1/P2/P3 candidate selection.
    pub top_processes: Vec<ProcRow>,
    pub browser_total_gb: f64,
    pub browser_kind: BrowserKind,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum BrowserKind {
    None,
    Chrome,
    Safari,
    Firefox,
}

/// Rule-engine config — pulled from `Settings`. Defaults track the Python file.
#[derive(Debug, Clone)]
pub struct Thresholds {
    pub warn: u32,         // mem_level WARN threshold (default 40)
    pub crit: u32,         // mem_level CRIT threshold (default 15)
    pub p0_offset: u32,    // P0 fires below warn + p0_offset (default 20 → 60)
    pub p0_age_secs: u64,  // headless Chrome must be older than this (default 600)
    pub idle_cpu_pct: f32, // P2 idle CPU cutoff (default 1.0)
    pub min_age_secs: u64, // P2/P3 only kill processes older than this (default 300)
    pub swap_warn_pct: u32,
    pub swap_crit_pct: u32,
    pub compressed_warn_gb: f64,
    pub compressed_crit_gb: f64,
    pub browser_tab_warn_gb: f64,
}

impl Default for Thresholds {
    fn default() -> Self {
        Self {
            warn: 40,
            crit: 15,
            p0_offset: 20,
            p0_age_secs: 600,
            idle_cpu_pct: 1.0,
            min_age_secs: 300,
            swap_warn_pct: 70,
            swap_crit_pct: 85,
            compressed_warn_gb: 5.0,
            compressed_crit_gb: 8.0,
            browser_tab_warn_gb: 2.0,
        }
    }
}

/// Priority lane the action belongs to. Used for log/observability and to
/// stop higher-impact rules from firing when a lower-impact action would do.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum Priority {
    P0, // stale headless chrome (cheap, never user-impacting)
    P1, // expendable apps + browser renderers (presence-aware)
    P2, // idle Claude Code (CRIT only)
    P3, // active Claude Code (CRIT only, last resort)
    Sweep, // orthogonal: compressed / swap / orphan / orbstack
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum NotifyLevel {
    Info,
    Warn,
    Crit,
}

/// Decision unit. `actions.rs` matches on this enum and decides whether to
/// fire (gated by `dry_run`).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Action {
    /// SIGTERM a process. `actions.rs` will skip if `dry_run=true`.
    KillProcess {
        pid: i32,
        name: String,
        reason: String,
        priority: Priority,
        rss_mb: u64,
    },
    /// Close inactive Chrome tabs via AppleScript. **DISABLED in current
    /// config (少爺規則: 永不 close tab)** — kept for completeness but the
    /// rule engine never emits it. Browser cleanup goes through
    /// `KillBrowserRenderers` instead.
    #[allow(dead_code)]
    CloseTabs {
        browser: BrowserKind,
        max_close: u32,
    },
    /// Kill aging browser renderer/GPU helpers.
    KillBrowserRenderers {
        browser: BrowserKind,
        reason: String,
    },
    /// Send a macOS notification via terminal-notifier or osascript.
    Notify {
        level: NotifyLevel,
        title: String,
        message: String,
        group: String,
    },
    /// No-op — included so callers can record "considered but skipped".
    NoOp { reason: String },
}

/// Pure rule engine: snapshot → action plan.
///
/// Mirrors Python `MemoryGuardian.run()` (lines 1077-1325) + presence gating.
pub fn decide(snap: &Snapshot, presence: Presence, th: &Thresholds) -> Vec<Action> {
    let mut plan: Vec<Action> = Vec::new();

    let mem_level = snap.mem_level;
    let is_warn = mem_level <= th.warn;
    let is_crit = mem_level <= th.crit;
    let p0_threshold = th.warn + th.p0_offset;
    let is_p0_window = mem_level < p0_threshold;

    // ── P0: stale headless Chrome (relaxed threshold) ──
    if is_p0_window {
        for p in &snap.top_processes {
            if p.command.contains("--headless") && p.age_secs > th.p0_age_secs {
                plan.push(Action::KillProcess {
                    pid: p.pid,
                    name: p.name.clone(),
                    reason: format!(
                        "P0 stale headless (age={}s, level={})",
                        p.age_secs, mem_level
                    ),
                    priority: Priority::P0,
                    rss_mb: p.rss_mb,
                });
            }
        }
    }

    // ── Browser pressure (presence-aware) ──
    // Only fires when memory is at WARN+ AND browser is bloated.
    if is_warn && snap.browser_total_gb >= th.browser_tab_warn_gb && snap.browser_kind != BrowserKind::None {
        match (presence, is_crit) {
            // CRIT: always nuke renderers regardless of presence
            (_, true) => {
                plan.push(Action::KillBrowserRenderers {
                    browser: snap.browser_kind,
                    reason: format!(
                        "browser CRIT level={} total={:.1}GB",
                        mem_level, snap.browser_total_gb
                    ),
                });
            }
            (Presence::Present, false) => {
                // Notify only — never auto-touch browser when 少爺 is here.
                plan.push(Action::Notify {
                    level: NotifyLevel::Warn,
                    title: "Memory Guardian".into(),
                    message: format!(
                        "Chrome {:.1}GB — 記憶體偏高,建議手動關閉分頁",
                        snap.browser_total_gb
                    ),
                    group: "browser-memory".into(),
                });
            }
            (Presence::BriefAway, false) => {
                // 少爺規則: 不再用 AppleScript close tab. Notify only.
                plan.push(Action::Notify {
                    level: NotifyLevel::Warn,
                    title: "Memory Guardian".into(),
                    message: format!(
                        "Chrome {:.1}GB — 短暫離開,等離開更久才會清理",
                        snap.browser_total_gb
                    ),
                    group: "browser-memory".into(),
                });
            }
            (Presence::Away, false) | (Presence::Unknown, false) => {
                // Away → kill renderers (preserve tabs as unloaded)
                plan.push(Action::KillBrowserRenderers {
                    browser: snap.browser_kind,
                    reason: format!(
                        "browser AWAY level={} total={:.1}GB",
                        mem_level, snap.browser_total_gb
                    ),
                });
            }
        }
    }

    // ── P1: expendable apps (gated by presence) ──
    // 'present' + non-CRIT → skip kills. Other states proceed.
    if is_warn {
        let allow_p1_kills = matches!(presence, Presence::Away | Presence::Unknown) || is_crit;
        if allow_p1_kills {
            const EXPENDABLE_PATTERNS: &[(&str, &str)] = &[
                ("LineCall", "LINE Call"),
                ("LINE", "LINE"),
                ("Visual Studio Code", "VS Code"),
                ("Antigravity", "Antigravity"),
                ("openclaw-gateway", "OpenClaw"),
                ("AltServer", "AltServer"),
            ];
            for p in &snap.top_processes {
                for (pat, label) in EXPENDABLE_PATTERNS {
                    if p.command.contains(pat) || p.name.contains(pat) {
                        plan.push(Action::KillProcess {
                            pid: p.pid,
                            name: label.to_string(),
                            reason: format!(
                                "P1 expendable presence={:?} level={}",
                                presence, mem_level
                            ),
                            priority: Priority::P1,
                            rss_mb: p.rss_mb,
                        });
                        break;
                    }
                }
            }
        }
    }

    // ── P2: idle Claude Code (CRIT only) ──
    if is_crit {
        for p in &snap.top_processes {
            let is_claude = p.name == "claude" || p.command.contains("claude");
            if is_claude && p.age_secs > th.min_age_secs && p.cpu_pct < th.idle_cpu_pct {
                plan.push(Action::KillProcess {
                    pid: p.pid,
                    name: "Claude Code (idle)".into(),
                    reason: format!(
                        "P2 idle claude cpu={:.1}% level={}",
                        p.cpu_pct, mem_level
                    ),
                    priority: Priority::P2,
                    rss_mb: p.rss_mb,
                });
            }
        }
    }

    // ── P3: active Claude Code (CRIT only, last resort) ──
    if is_crit {
        for p in &snap.top_processes {
            let is_claude = p.name == "claude" || p.command.contains("claude");
            if is_claude && p.age_secs > th.min_age_secs && p.cpu_pct >= th.idle_cpu_pct {
                plan.push(Action::KillProcess {
                    pid: p.pid,
                    name: "Claude Code (active)".into(),
                    reason: format!(
                        "P3 active claude cpu={:.1}% level={} (last resort)",
                        p.cpu_pct, mem_level
                    ),
                    priority: Priority::P3,
                    rss_mb: p.rss_mb,
                });
            }
        }
    }

    // ── Orthogonal sweeps: compressed memory + swap notifications ──
    if snap.compressed_gb >= th.compressed_crit_gb {
        plan.push(Action::Notify {
            level: NotifyLevel::Crit,
            title: "Memory Guardian ⚠️".into(),
            message: format!(
                "壓縮記憶體 {:.1}GB ≥ 臨界值 {:.1}GB,系統可能不穩定",
                snap.compressed_gb, th.compressed_crit_gb
            ),
            group: "compressed-crit".into(),
        });
    } else if snap.compressed_gb >= th.compressed_warn_gb {
        plan.push(Action::Notify {
            level: NotifyLevel::Warn,
            title: "Memory Guardian".into(),
            message: format!(
                "壓縮記憶體 {:.1}GB ≥ {:.1}GB",
                snap.compressed_gb, th.compressed_warn_gb
            ),
            group: "compressed-warn".into(),
        });
    }

    if snap.swap_used_pct >= th.swap_crit_pct {
        plan.push(Action::Notify {
            level: NotifyLevel::Crit,
            title: "Memory Guardian ⚠️".into(),
            message: format!(
                "Swap {}% ({:.1}GB) — 請檢查 bloated orphans",
                snap.swap_used_pct, snap.swap_used_gb
            ),
            group: "swap-crit".into(),
        });
    } else if snap.swap_used_pct >= th.swap_warn_pct {
        plan.push(Action::Notify {
            level: NotifyLevel::Warn,
            title: "Memory Guardian".into(),
            message: format!(
                "Swap {}% ({:.1}GB)",
                snap.swap_used_pct, snap.swap_used_gb
            ),
            group: "swap-warn".into(),
        });
    }

    if plan.is_empty() {
        plan.push(Action::NoOp {
            reason: format!(
                "level={} presence={:?} all-clear",
                mem_level, presence
            ),
        });
    }

    plan
}

#[cfg(test)]
mod tests {
    use super::*;

    fn proc(pid: i32, name: &str, cmd: &str, rss_mb: u64, cpu: f32, age: u64) -> ProcRow {
        ProcRow {
            pid,
            name: name.into(),
            command: cmd.into(),
            rss_mb,
            cpu_pct: cpu,
            age_secs: age,
        }
    }

    fn empty_snap(level: u32) -> Snapshot {
        Snapshot {
            mem_level: level,
            compressed_gb: 0.0,
            swap_used_gb: 0.0,
            swap_used_pct: 0,
            idle_seconds: 0,
            top_processes: vec![],
            browser_total_gb: 0.0,
            browser_kind: BrowserKind::None,
        }
    }

    #[test]
    fn ok_state_emits_noop() {
        let th = Thresholds::default();
        let plan = decide(&empty_snap(80), Presence::Present, &th);
        assert!(matches!(plan[..], [Action::NoOp { .. }]));
    }

    #[test]
    fn p0_kills_stale_headless_at_relaxed_threshold() {
        // mem_level=55 < warn(40)+offset(20)=60 → P0 fires even though we're above warn.
        let th = Thresholds::default();
        let mut snap = empty_snap(55);
        snap.top_processes = vec![
            proc(101, "Chrome", "/Applications/Chromium --headless --remote-debugging-port", 800, 5.0, 1200),
            proc(102, "Chrome", "Google Chrome.app/Contents/MacOS/Google Chrome --type=renderer", 600, 1.0, 50), // young, not headless
        ];
        let plan = decide(&snap, Presence::Present, &th);
        let kills: Vec<_> = plan.iter().filter_map(|a| match a {
            Action::KillProcess { pid, priority: Priority::P0, .. } => Some(*pid),
            _ => None,
        }).collect();
        assert_eq!(kills, vec![101]);
    }

    #[test]
    fn p1_skipped_when_present_and_not_crit() {
        let th = Thresholds::default();
        let mut snap = empty_snap(35); // WARN but not CRIT
        snap.top_processes = vec![proc(200, "LINE", "LINE.app/Contents/MacOS/LINE", 1500, 3.0, 7200)];
        let plan = decide(&snap, Presence::Present, &th);
        assert!(!plan.iter().any(|a| matches!(a, Action::KillProcess { priority: Priority::P1, .. })));
    }

    #[test]
    fn p1_fires_when_away() {
        let th = Thresholds::default();
        let mut snap = empty_snap(35);
        snap.top_processes = vec![
            proc(200, "LINE", "LINE.app/Contents/MacOS/LINE", 1500, 3.0, 7200),
            proc(201, "VSCode", "Visual Studio Code Helper", 800, 2.0, 7200),
        ];
        let plan = decide(&snap, Presence::Away, &th);
        let p1: Vec<_> = plan.iter().filter_map(|a| match a {
            Action::KillProcess { pid, priority: Priority::P1, .. } => Some(*pid),
            _ => None,
        }).collect();
        assert!(p1.contains(&200));
        assert!(p1.contains(&201));
    }

    #[test]
    fn p2_p3_only_fire_on_crit() {
        let th = Thresholds::default();
        let claude_idle = proc(300, "claude", "/usr/local/bin/claude", 4000, 0.2, 7200);
        let claude_busy = proc(301, "claude", "/usr/local/bin/claude", 4000, 25.0, 7200);

        // WARN — should NOT touch Claude
        let mut snap = empty_snap(35);
        snap.top_processes = vec![claude_idle.clone(), claude_busy.clone()];
        let plan = decide(&snap, Presence::Away, &th);
        assert!(!plan.iter().any(|a| matches!(
            a,
            Action::KillProcess { priority: Priority::P2, .. } | Action::KillProcess { priority: Priority::P3, .. }
        )));

        // CRIT — should fire both P2 (idle) and P3 (active)
        let mut snap = empty_snap(10);
        snap.top_processes = vec![claude_idle, claude_busy];
        let plan = decide(&snap, Presence::Away, &th);
        let priorities: Vec<_> = plan.iter().filter_map(|a| match a {
            Action::KillProcess { priority, pid, .. } => Some((*priority, *pid)),
            _ => None,
        }).collect();
        assert!(priorities.contains(&(Priority::P2, 300)));
        assert!(priorities.contains(&(Priority::P3, 301)));
    }

    #[test]
    fn browser_present_warn_emits_notify_only() {
        let th = Thresholds::default();
        let mut snap = empty_snap(35);
        snap.browser_kind = BrowserKind::Chrome;
        snap.browser_total_gb = 4.5;
        let plan = decide(&snap, Presence::Present, &th);
        assert!(plan.iter().any(|a| matches!(a, Action::Notify { group, .. } if group == "browser-memory")));
        assert!(!plan.iter().any(|a| matches!(a, Action::KillBrowserRenderers { .. })));
    }

    #[test]
    fn browser_away_kills_renderers() {
        let th = Thresholds::default();
        let mut snap = empty_snap(35);
        snap.browser_kind = BrowserKind::Chrome;
        snap.browser_total_gb = 4.5;
        let plan = decide(&snap, Presence::Away, &th);
        assert!(plan.iter().any(|a| matches!(a, Action::KillBrowserRenderers { browser: BrowserKind::Chrome, .. })));
    }

    #[test]
    fn browser_crit_overrides_presence() {
        let th = Thresholds::default();
        let mut snap = empty_snap(10); // CRIT
        snap.browser_kind = BrowserKind::Chrome;
        snap.browser_total_gb = 3.0;
        // 少爺在場 + CRIT → 還是要殺 renderers
        let plan = decide(&snap, Presence::Present, &th);
        assert!(plan.iter().any(|a| matches!(a, Action::KillBrowserRenderers { .. })));
    }

    #[test]
    fn compressed_crit_emits_crit_notify() {
        let th = Thresholds::default();
        let mut snap = empty_snap(80); // OK level
        snap.compressed_gb = 9.0; // ≥ crit (8.0)
        let plan = decide(&snap, Presence::Present, &th);
        assert!(plan.iter().any(|a| matches!(
            a,
            Action::Notify { level: NotifyLevel::Crit, group, .. } if group == "compressed-crit"
        )));
    }

    #[test]
    fn swap_warn_does_not_imply_kill() {
        let th = Thresholds::default();
        let mut snap = empty_snap(80);
        snap.swap_used_pct = 75;
        snap.swap_used_gb = 8.0;
        let plan = decide(&snap, Presence::Present, &th);
        assert!(plan.iter().any(|a| matches!(a, Action::Notify { group, .. } if group == "swap-warn")));
        assert!(!plan.iter().any(|a| matches!(a, Action::KillProcess { .. })));
    }

    #[test]
    fn min_age_protects_young_claude() {
        let th = Thresholds::default();
        let mut snap = empty_snap(10); // CRIT
        snap.top_processes = vec![proc(400, "claude", "claude", 4000, 0.1, 60)]; // age < min_age
        let plan = decide(&snap, Presence::Away, &th);
        assert!(!plan.iter().any(|a| matches!(a, Action::KillProcess { priority: Priority::P2, .. })));
    }
}
