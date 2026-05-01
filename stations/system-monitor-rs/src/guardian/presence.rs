//! User-presence classifier. Mirrors `memory_guardian.py::_classify_presence()`
//! and `_get_user_idle_seconds()`.
//!
//! idle < 300s (5min) → Present
//! idle 300-900s      → BriefAway
//! idle ≥ 900s        → Away
//! idle < 0           → Unknown (cannot read pmset/HIDIdleTime)

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Presence {
    Present,
    BriefAway,
    Away,
    Unknown,
}

const PRESENT_IDLE_SEC: i64 = 300;
const AWAY_IDLE_SEC: i64 = 900;

/// Classify presence from idle seconds. `idle_seconds < 0` ⇒ Unknown
/// (e.g. pmset + HIDIdleTime both unreadable).
pub fn classify_presence(idle_seconds: i64) -> Presence {
    if idle_seconds < 0 {
        Presence::Unknown
    } else if idle_seconds < PRESENT_IDLE_SEC {
        Presence::Present
    } else if idle_seconds < AWAY_IDLE_SEC {
        Presence::BriefAway
    } else {
        Presence::Away
    }
}

/// Read user idle seconds. Prefers `pmset -g assertions` UserIsActive flag
/// (covers Universal Control / KVM scenarios where HIDIdleTime never resets);
/// falls back to `ioreg HIDIdleTime`. Returns -1 when both signals fail.
///
/// Mirrors Python `_get_user_idle_seconds()` (memory_guardian.py:272-290).
pub fn read_user_idle_seconds() -> i64 {
    // Step 1: pmset UserIsActive
    let pmset_active = pmset_user_is_active();
    if pmset_active == Some(true) {
        return 0;
    }

    // Step 2: HIDIdleTime fallback
    if let Some(secs) = hid_idle_seconds() {
        return secs as i64;
    }

    // pmset said False but HID was unreadable → user is inactive but we
    // don't know how long. Use 99999 to land in Away. Mirrors Python.
    if pmset_active == Some(false) {
        return 99_999;
    }
    -1
}

fn pmset_user_is_active() -> Option<bool> {
    let out = std::process::Command::new("pmset")
        .args(["-g", "assertions"])
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    for line in s.lines() {
        let trimmed = line.trim_start();
        if let Some(rest) = trimmed.strip_prefix("UserIsActive") {
            let val = rest.trim();
            if val.starts_with('1') {
                return Some(true);
            }
            if val.starts_with('0') {
                return Some(false);
            }
        }
    }
    None
}

fn hid_idle_seconds() -> Option<u64> {
    let out = std::process::Command::new("sh")
        .arg("-c")
        .arg("ioreg -c IOHIDSystem -r 2>/dev/null | grep HIDIdleTime")
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    let line = s.lines().next()?;
    // Format: "    "HIDIdleTime" = 12345678901"
    let eq_idx = line.find('=')?;
    let num_str = line[eq_idx + 1..].trim();
    let nanos: u64 = num_str.parse().ok()?;
    Some(nanos / 1_000_000_000)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn negative_idle_is_unknown() {
        assert_eq!(classify_presence(-1), Presence::Unknown);
    }

    #[test]
    fn zero_is_present() {
        assert_eq!(classify_presence(0), Presence::Present);
    }

    #[test]
    fn boundary_300_is_brief_away() {
        // <300 = present, ≥300 = brief_away
        assert_eq!(classify_presence(299), Presence::Present);
        assert_eq!(classify_presence(300), Presence::BriefAway);
    }

    #[test]
    fn boundary_900_is_away() {
        assert_eq!(classify_presence(899), Presence::BriefAway);
        assert_eq!(classify_presence(900), Presence::Away);
    }

    #[test]
    fn far_future_is_away() {
        assert_eq!(classify_presence(99_999), Presence::Away);
    }
}
