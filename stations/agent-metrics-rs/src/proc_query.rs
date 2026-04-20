//! Shared `ps` parsing helpers used by guardian + sweep.
//!
//! All readings come from `ps -eo ...` so output matches Python word-for-word.

use anyhow::Result;
use tokio::process::Command;

#[derive(Debug, Clone)]
pub struct ProcRow {
    pub pid: i32,
    pub ppid: i32,
    pub rss_kb: i64,
    pub cpu: f64,
    pub etime_sec: i64,
    pub command: String,
}

#[derive(Debug, Clone)]
pub struct SimpleProc {
    pub pid: i32,
    pub rss_kb: i64,
    pub cpu: f64,
}

#[derive(Debug, Clone)]
pub struct ClaudeProc {
    pub pid: i32,
    pub rss_kb: i64,
    pub cpu: f64,
    pub start_epoch: i64,
}

pub async fn run_ps(args: &[&str]) -> Result<String> {
    let out = Command::new("ps").args(args).output().await?;
    if !out.status.success() {
        anyhow::bail!("ps {args:?} failed: {}", String::from_utf8_lossy(&out.stderr));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// `ps -eo pid=,ppid=,rss=,%cpu=,etime=,command=` parsing — used by sweep.
pub async fn process_details() -> Result<Vec<ProcRow>> {
    let raw = run_ps(&["-eo", "pid=,ppid=,rss=,%cpu=,etime=,command="]).await?;
    let mut rows = Vec::new();
    for raw_line in raw.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.contains("sweep") {
            continue;
        }
        let mut it = line.splitn(6, char::is_whitespace).filter(|s| !s.is_empty());
        let pid: i32 = match it.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let ppid: i32 = match it.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let rss_kb: i64 = match it.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let cpu: f64 = match it.next().and_then(|s| s.parse().ok()) {
            Some(v) => v,
            None => continue,
        };
        let etime_str = match it.next() {
            Some(v) => v.to_string(),
            None => continue,
        };
        let command = match it.next() {
            Some(v) => v.to_string(),
            None => continue,
        };
        rows.push(ProcRow {
            pid,
            ppid,
            rss_kb,
            cpu,
            etime_sec: parse_etime(&etime_str),
            command,
        });
    }
    Ok(rows)
}

/// Match by substring (Python `pattern in line`); excludes `grep` + `sweep`.
pub async fn find_processes(pattern: &str) -> Vec<SimpleProc> {
    let raw = match run_ps(&["-eo", "pid=,rss=,%cpu=,command="]).await {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let mut rows = Vec::new();
    for line in raw.lines() {
        if line.contains(pattern) && !line.contains("grep") && !line.contains("sweep") {
            let parts: Vec<&str> = line.splitn(4, char::is_whitespace).filter(|s| !s.is_empty()).collect();
            if parts.len() < 3 {
                continue;
            }
            let pid: i32 = match parts[0].parse() {
                Ok(v) => v,
                Err(_) => continue,
            };
            let rss_kb: i64 = parts[1].parse().unwrap_or(0);
            let cpu: f64 = parts[2].parse().unwrap_or(0.0);
            rows.push(SimpleProc { pid, rss_kb, cpu });
        }
    }
    rows
}

/// `ps -eo pid=,rss=,%cpu=,lstart=,comm=` filtered to `comm == "claude"`.
pub async fn find_claude_processes() -> Vec<ClaudeProc> {
    let raw = match run_ps(&["-eo", "pid=,rss=,%cpu=,lstart=,comm="]).await {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let mut rows = Vec::new();
    for line in raw.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() {
            continue;
        }
        let comm = parts[parts.len() - 1];
        if comm != "claude" {
            continue;
        }
        if parts.len() < 9 {
            continue;
        }
        let pid: i32 = parts[0].parse().unwrap_or(0);
        let rss_kb: i64 = parts[1].parse().unwrap_or(0);
        let cpu: f64 = parts[2].parse().unwrap_or(0.0);

        // lstart is 5 fields: "Wed Apr  9 10:15:30"
        let lstart = parts[3..8].join(" ");
        let start_epoch = parse_lstart(&lstart).unwrap_or(0);

        rows.push(ClaudeProc {
            pid,
            rss_kb,
            cpu,
            start_epoch,
        });
    }
    rows
}

/// `ps -o ppid= -p <pid>` — single-pid parent lookup.
pub async fn ppid_of(pid: i32) -> i32 {
    match run_ps(&["-o", "ppid=", "-p", &pid.to_string()]).await {
        Ok(s) => s.trim().parse().unwrap_or(-1),
        Err(_) => -1,
    }
}

/// Parse macOS `ps etime=` format. Supports:
///   - "DD-HH:MM:SS"
///   - "HH:MM:SS"
///   - "MM:SS"
pub fn parse_etime(s: &str) -> i64 {
    let s = s.trim();
    if s.is_empty() {
        return 0;
    }
    if let Some(idx) = s.find('-') {
        let days: i64 = s[..idx].parse().unwrap_or(0);
        let rest = &s[idx + 1..];
        let parts: Vec<&str> = rest.split(':').collect();
        if parts.len() == 3 {
            let h: i64 = parts[0].parse().unwrap_or(0);
            let m: i64 = parts[1].parse().unwrap_or(0);
            let sec: i64 = parts[2].parse().unwrap_or(0);
            return days * 86400 + h * 3600 + m * 60 + sec;
        }
    }
    let parts: Vec<&str> = s.split(':').collect();
    match parts.len() {
        3 => {
            let h: i64 = parts[0].parse().unwrap_or(0);
            let m: i64 = parts[1].parse().unwrap_or(0);
            let sec: i64 = parts[2].parse().unwrap_or(0);
            h * 3600 + m * 60 + sec
        }
        2 => {
            let m: i64 = parts[0].parse().unwrap_or(0);
            let sec: i64 = parts[1].parse().unwrap_or(0);
            m * 60 + sec
        }
        _ => 0,
    }
}

/// Parse the `ps -eo lstart=` format ("Wed Apr  9 10:15:30 2026") into UNIX epoch.
///
/// IMPORTANT: `ps lstart` emits **local** wall-clock time. Python's
/// `datetime.strptime(...).timestamp()` interprets a naive datetime as local
/// and returns UTC epoch — so we must convert via `Local`, not `Utc`.
/// Treating it as UTC offsets the returned epoch by the local tz, which would
/// shift the guardian Claude-process age comparison by hours.
///
/// Day-of-month handling: `ps` left-pads single-digit days with a space
/// ("Apr  9"). chrono's `%e` does not accept this padding form, so we collapse
/// runs of whitespace to one and zero-pad the day before applying `%d`.
pub fn parse_lstart(s: &str) -> Option<i64> {
    use chrono::{Local, NaiveDateTime, TimeZone};

    let normalized = normalize_lstart(s)?;

    // Try with year first (full lstart output)
    if let Ok(dt) = NaiveDateTime::parse_from_str(&normalized, "%a %b %d %H:%M:%S %Y") {
        return Local
            .from_local_datetime(&dt)
            .single()
            .map(|d| d.timestamp());
    }
    // ps may omit year — assume current local year
    let now = Local::now();
    let with_year = format!("{} {}", normalized, now.format("%Y"));
    if let Ok(dt) = NaiveDateTime::parse_from_str(&with_year, "%a %b %d %H:%M:%S %Y") {
        return Local
            .from_local_datetime(&dt)
            .single()
            .map(|d| d.timestamp());
    }
    None
}

/// Collapse multiple whitespace and zero-pad the day-of-month token, e.g.
///   "Wed Apr  9 10:15:30 2026"  →  "Wed Apr 09 10:15:30 2026"
fn normalize_lstart(s: &str) -> Option<String> {
    let parts: Vec<&str> = s.split_whitespace().collect();
    if parts.len() < 4 {
        return None;
    }
    // Layout: [Wday, Mon, Day, HH:MM:SS, Year?]
    let day = parts[2];
    let day_padded = if day.len() == 1 && day.chars().all(|c| c.is_ascii_digit()) {
        format!("0{}", day)
    } else {
        day.to_string()
    };
    let mut rebuilt: Vec<String> = parts.iter().map(|s| s.to_string()).collect();
    rebuilt[2] = day_padded;
    Some(rebuilt.join(" "))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn etime_dd_hh_mm_ss() {
        assert_eq!(parse_etime("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5);
    }

    #[test]
    fn etime_hh_mm_ss() {
        assert_eq!(parse_etime("01:02:03"), 3723);
    }

    #[test]
    fn etime_mm_ss() {
        assert_eq!(parse_etime("12:34"), 12 * 60 + 34);
    }

    #[test]
    fn etime_empty() {
        assert_eq!(parse_etime(""), 0);
    }

    #[test]
    fn lstart_matches_python_local_tz() {
        // Python: datetime.strptime("Wed Apr 16 12:34:56 2025", "%c").timestamp()
        // Result depends on machine local TZ — we just assert the Rust epoch
        // matches what the same conversion yields locally.
        use chrono::{Local, NaiveDate, TimeZone};
        let expected = Local
            .from_local_datetime(
                &NaiveDate::from_ymd_opt(2025, 4, 16)
                    .unwrap()
                    .and_hms_opt(12, 34, 56)
                    .unwrap(),
            )
            .single()
            .unwrap()
            .timestamp();
        let got = parse_lstart("Wed Apr 16 12:34:56 2025").expect("parse");
        assert_eq!(got, expected, "parse_lstart must use local tz");
    }

    #[test]
    fn lstart_handles_double_space_day() {
        // ps left-pads single-digit days with an extra space.
        // Apr 9 2026 is a Thursday — chrono validates %a against date.
        assert!(parse_lstart("Thu Apr  9 10:15:30 2026").is_some());
    }

    #[test]
    fn lstart_year_omitted_uses_current_year() {
        // %c without year — should fall back to current Local year.
        // Use today's date so day-of-week always matches.
        use chrono::{Datelike, Local};
        let now = Local::now();
        let weekday = now.format("%a").to_string();
        let month = now.format("%b").to_string();
        let day = now.day();
        let s = format!("{} {} {} 12:34:56", weekday, month, day);
        assert!(parse_lstart(&s).is_some(), "failed for input: {s}");
    }
}
