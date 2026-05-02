//! `vmmap -summary {pid}` parser. Mirrors Python
//! `_get_process_footprint_gb()` (memory_guardian.py:206-232).
//!
//! Why footprint and not RSS: macOS pages out idle leaks; RSS shrinks but
//! "Physical footprint" still surfaces them. This catches inline-python
//! heredoc orphans whose RSS lies (incident: 2026-05-01, two leaks at 30 GB
//! each pushed swap to 95 %).

use std::process::Command;
use std::time::Duration;

/// Returns the process's physical footprint in GB, or None if vmmap fails
/// (process exited / sandbox-blocked / permission denied).
pub fn get_footprint_gb(pid: i32) -> Option<f64> {
    let out = run_with_timeout(pid, Duration::from_secs(5))?;
    parse_footprint_gb(&out)
}

fn run_with_timeout(pid: i32, _timeout: Duration) -> Option<String> {
    // std::process has no built-in timeout; vmmap usually returns in <1s.
    // If a hung pid becomes a real problem we can swap in `timeout 5 vmmap …`.
    let out = Command::new("/usr/bin/vmmap")
        .args(["-summary", &pid.to_string()])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8(out.stdout).ok()
}

/// Parse the "Physical footprint:" line. Handles G/M/K suffix.
pub(crate) fn parse_footprint_gb(stdout: &str) -> Option<f64> {
    for line in stdout.lines() {
        if let Some(rest) = line.trim_start().strip_prefix("Physical footprint:") {
            return parse_size_to_gb(rest.trim());
        }
    }
    None
}

fn parse_size_to_gb(token: &str) -> Option<f64> {
    // Examples:  "30.5G",  "812.4M",  "987K",  "1.2 G",  "30.5G\n(peak..."
    // Trim trailing whitespace / parens / non-size chars after the first
    // size token (vmmap sometimes appends "(peak: ...)" on the same line).
    let head = token
        .split(|c: char| c == '(' || c == ',' || c == '\n')
        .next()?
        .trim();
    let unit = head.chars().rev().find(|c| c.is_alphabetic())?;
    let unit_pos = head.rfind(unit)?;
    let num: f64 = head[..unit_pos].trim().parse().ok()?;
    Some(match unit {
        'G' | 'g' => num,
        'M' | 'm' => num / 1024.0,
        'K' | 'k' => num / (1024.0 * 1024.0),
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "\
Process:         python3 [12345]
Physical footprint:           30.5G
Physical footprint (peak):    31.0G
";

    #[test]
    fn parses_gb() {
        assert_eq!(parse_footprint_gb(SAMPLE), Some(30.5));
    }

    #[test]
    fn parses_mb_to_gb() {
        let s = "Physical footprint:           812.4M\n";
        let v = parse_footprint_gb(s).unwrap();
        assert!((v - 812.4 / 1024.0).abs() < 1e-6);
    }

    #[test]
    fn missing_line_returns_none() {
        assert_eq!(parse_footprint_gb("nothing here"), None);
    }
}
