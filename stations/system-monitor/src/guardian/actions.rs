//! Side-effect layer. Consumes the action plan from `thresholds::decide()`
//! and (when `dry_run=false`) actually fires SIGTERM / AppleScript /
//! notifications.
//!
//! All actions emit a JSONL line to `<data_dir>/logs/guardian.log` regardless
//! of `dry_run`. Schema:
//!     {timestamp, action, pid, name, reason, dry_run, result}

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use chrono::Utc;
use serde_json::{json, Value};

use super::thresholds::{Action, BrowserKind};

/// Executor — owns the log path and the dry_run flag.
#[derive(Debug)]
pub struct Executor {
    pub log_path: PathBuf,
    pub dry_run: bool,
}

impl Executor {
    pub fn new(log_path: impl AsRef<Path>, dry_run: bool) -> Self {
        Self {
            log_path: log_path.as_ref().to_path_buf(),
            dry_run,
        }
    }

    /// Execute every action in the plan. Returns the recorded log entries
    /// (so `tick()` can include them in the heartbeat without re-reading
    /// the file).
    pub fn run(&self, plan: &[Action]) -> Result<Vec<Value>> {
        if let Some(parent) = self.log_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let mut entries: Vec<Value> = Vec::with_capacity(plan.len());
        for action in plan {
            let entry = self.execute_one(action);
            self.append_log(&entry);
            entries.push(entry);
        }
        Ok(entries)
    }

    fn execute_one(&self, action: &Action) -> Value {
        let ts = Utc::now().to_rfc3339();
        match action {
            Action::KillProcess {
                pid,
                name,
                reason,
                priority,
                rss_mb,
            } => {
                let result = if self.dry_run {
                    "dry_run".to_string()
                } else {
                    match kill_process(*pid, false) {
                        Ok(_) => "killed".to_string(),
                        Err(e) => format!("error:{e}"),
                    }
                };
                json!({
                    "timestamp": ts,
                    "action": "kill_process",
                    "pid": pid,
                    "name": name,
                    "reason": reason,
                    "priority": format!("{:?}", priority),
                    "rss_mb": rss_mb,
                    "dry_run": self.dry_run,
                    "result": result,
                })
            }
            Action::CloseTabs {
                browser,
                max_close,
            } => {
                // 少爺規則: 永不 close tab. We log it but never execute even
                // when dry_run=false.
                json!({
                    "timestamp": ts,
                    "action": "close_tabs",
                    "browser": format!("{:?}", browser),
                    "max_close": max_close,
                    "dry_run": self.dry_run,
                    "result": "disabled_by_policy",
                })
            }
            Action::KillBrowserRenderers { browser, reason } => {
                let summary = if self.dry_run {
                    BrowserKillSummary::default()
                } else {
                    kill_browser_renderers(*browser)
                };
                json!({
                    "timestamp": ts,
                    "action": "kill_browser_renderers",
                    "browser": format!("{:?}", browser),
                    "reason": reason,
                    "dry_run": self.dry_run,
                    "killed_count": summary.killed,
                    "freed_mb": summary.freed_mb,
                    "errors": summary.errors,
                })
            }
            Action::Notify {
                level,
                title,
                message,
                group,
            } => {
                let result = if self.dry_run {
                    "dry_run".to_string()
                } else {
                    match send_notification(title, message, group) {
                        Ok(via) => format!("sent:{via}"),
                        Err(e) => format!("error:{e}"),
                    }
                };
                json!({
                    "timestamp": ts,
                    "action": "notify",
                    "level": format!("{:?}", level),
                    "title": title,
                    "message": message,
                    "group": group,
                    "dry_run": self.dry_run,
                    "result": result,
                })
            }
            Action::NoOp { reason } => json!({
                "timestamp": ts,
                "action": "noop",
                "reason": reason,
                "dry_run": self.dry_run,
                "result": "skipped",
            }),
        }
    }

    fn append_log(&self, entry: &Value) {
        if let Ok(mut f) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path)
        {
            let _ = writeln!(f, "{}", entry);
        }
    }
}

// ── lower-level primitives ───────────────────────────────────────────────

#[derive(Debug, Default)]
struct BrowserKillSummary {
    killed: u32,
    freed_mb: u64,
    errors: Vec<String>,
}

/// SIGTERM by default. Set `force=true` for SIGKILL.
pub fn kill_process(pid: i32, force: bool) -> Result<()> {
    use nix::sys::signal::{kill, Signal};
    use nix::unistd::Pid;
    let sig = if force { Signal::SIGKILL } else { Signal::SIGTERM };
    kill(Pid::from_raw(pid), sig)?;
    Ok(())
}

/// Find Chrome Helper (Renderer/GPU) processes and SIGTERM the aging,
/// memory-heavy ones. Mirrors Python `_kill_browser_renderers()`.
fn kill_browser_renderers(browser: BrowserKind) -> BrowserKillSummary {
    let patterns: &[&str] = match browser {
        BrowserKind::Chrome => &[
            "Google Chrome Helper (Renderer)",
            "Google Chrome Helper (GPU)",
        ],
        BrowserKind::Safari => &["com.apple.WebKit.WebContent"],
        BrowserKind::Firefox => &["plugin-container"],
        BrowserKind::None => return BrowserKillSummary::default(),
    };

    let mut summary = BrowserKillSummary::default();
    for pat in patterns {
        for proc in find_processes(pat) {
            // Skip too-young or too-small renderers — keep recent tabs
            // around for the user.
            if proc.age_secs < 600 && proc.rss_mb < 200 {
                continue;
            }
            match kill_process(proc.pid, false) {
                Ok(_) => {
                    summary.killed += 1;
                    summary.freed_mb += proc.rss_mb;
                }
                Err(e) => {
                    summary.errors.push(format!("{}:{e}", proc.pid));
                }
            }
        }
    }
    summary
}

/// `osascript` AppleScript to close inactive Chrome tabs. **Currently
/// unused** by the rule engine (少爺規則: 永不 close tab) — kept for the
/// CRIT-only escape hatch and integration tests.
#[allow(dead_code)]
pub fn close_chrome_tabs(max_close: u32) -> Result<u32> {
    let script = format!(
        r#"
tell application "Google Chrome"
    set closedCount to 0
    repeat with w in windows
        set activeIdx to active tab index of w
        set tabCount to count of tabs of w
        repeat with i from tabCount to 1 by -1
            if i is not activeIdx and closedCount < {max_close} then
                close tab i of w
                set closedCount to closedCount + 1
            end if
        end repeat
    end repeat
    return closedCount
end tell
"#
    );
    let out = Command::new("osascript").args(["-e", &script]).output()?;
    if !out.status.success() {
        anyhow::bail!(
            "osascript failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        );
    }
    let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
    Ok(stdout.parse().unwrap_or(0))
}

/// Send a macOS notification. terminal-notifier preferred, osascript fallback.
fn send_notification(title: &str, message: &str, group: &str) -> Result<&'static str> {
    if Command::new("terminal-notifier")
        .args([
            "-title", title, "-message", message, "-group", group,
        ])
        .output()
        .ok()
        .map(|o| o.status.success())
        .unwrap_or(false)
    {
        return Ok("terminal-notifier");
    }

    let escaped_msg = message.replace('"', "\\\"");
    let escaped_title = title.replace('"', "\\\"");
    let script = format!(
        r#"display notification "{}" with title "{}""#,
        escaped_msg, escaped_title
    );
    Command::new("osascript")
        .args(["-e", &script])
        .output()?;
    Ok("osascript")
}

#[derive(Debug, Clone)]
struct ProcInfo {
    pid: i32,
    rss_mb: u64,
    age_secs: u64,
}

/// `ps -eo pid=,rss=,etime=,command=` filtered by command-line substring.
fn find_processes(pattern: &str) -> Vec<ProcInfo> {
    let out = Command::new("ps")
        .args(["-eo", "pid=,rss=,etime=,command="])
        .output();
    let stdout = match out {
        Ok(o) => String::from_utf8_lossy(&o.stdout).to_string(),
        Err(_) => return Vec::new(),
    };

    let mut results = Vec::new();
    for line in stdout.lines() {
        if !line.contains(pattern) {
            continue;
        }
        let mut it = line.split_whitespace();
        let pid: i32 = match it.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let rss_kb: u64 = match it.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let etime: &str = match it.next() {
            Some(v) => v,
            None => continue,
        };
        results.push(ProcInfo {
            pid,
            rss_mb: rss_kb / 1024,
            age_secs: parse_etime(etime),
        });
    }
    results
}

/// Parse `ps` etime format ([dd-]hh:mm:ss or mm:ss) into seconds.
fn parse_etime(s: &str) -> u64 {
    let (days, rest) = match s.split_once('-') {
        Some((d, r)) => (d.parse::<u64>().unwrap_or(0), r),
        None => (0, s),
    };
    let parts: Vec<&str> = rest.split(':').collect();
    let (h, m, sec) = match parts.as_slice() {
        [h, m, s] => (
            h.parse::<u64>().unwrap_or(0),
            m.parse::<u64>().unwrap_or(0),
            s.parse::<u64>().unwrap_or(0),
        ),
        [m, s] => (
            0,
            m.parse::<u64>().unwrap_or(0),
            s.parse::<u64>().unwrap_or(0),
        ),
        _ => (0, 0, 0),
    };
    days * 86_400 + h * 3_600 + m * 60 + sec
}

/// Convenience helper used by `mod.rs` heartbeat.
#[allow(dead_code)]
pub(crate) fn now_unix_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::thresholds::Priority;
    use std::env;

    fn temp_log(label: &str) -> PathBuf {
        // Per-test unique path so parallel tests don't race on the same file.
        let mut p = env::temp_dir();
        p.push(format!(
            "guardian-actions-test-{}-{}-{}.jsonl",
            std::process::id(),
            label,
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0),
        ));
        p
    }

    #[test]
    fn dry_run_logs_but_does_not_kill() {
        let log = temp_log("dry_run");
        let _ = std::fs::remove_file(&log);
        let exec = Executor::new(&log, true);
        let plan = vec![Action::KillProcess {
            pid: 999_999, // nonexistent — would fail without dry_run guard
            name: "fake".into(),
            reason: "test".into(),
            priority: Priority::P0,
            rss_mb: 100,
        }];
        let entries = exec.run(&plan).unwrap();
        assert_eq!(entries[0]["result"], "dry_run");
        let log_contents = std::fs::read_to_string(&log).unwrap();
        assert!(log_contents.contains("dry_run"));
        let _ = std::fs::remove_file(&log);
    }

    #[test]
    fn close_tabs_action_disabled_by_policy() {
        let log = temp_log("close_tabs");
        let _ = std::fs::remove_file(&log);
        let exec = Executor::new(&log, false);
        let plan = vec![Action::CloseTabs {
            browser: BrowserKind::Chrome,
            max_close: 5,
        }];
        let entries = exec.run(&plan).unwrap();
        assert_eq!(entries[0]["result"], "disabled_by_policy");
        let _ = std::fs::remove_file(&log);
    }

    #[test]
    fn etime_parses_compound_format() {
        assert_eq!(parse_etime("00:30"), 30);
        assert_eq!(parse_etime("5:00"), 300);
        assert_eq!(parse_etime("1:00:00"), 3_600);
        assert_eq!(parse_etime("2-03:04:05"), 2 * 86_400 + 3 * 3_600 + 4 * 60 + 5);
    }

    #[test]
    fn noop_action_records_skipped() {
        let log = temp_log("noop");
        let _ = std::fs::remove_file(&log);
        let exec = Executor::new(&log, true);
        let plan = vec![Action::NoOp { reason: "all clear".into() }];
        let entries = exec.run(&plan).unwrap();
        assert_eq!(entries[0]["result"], "skipped");
        let _ = std::fs::remove_file(&log);
    }
}
