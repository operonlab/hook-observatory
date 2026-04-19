//! LINE Desktop reader — Screenshot + OCR via stations/ocr service to extract SurveyCake URLs.
//!
//! Strategy mirrors `stations/auto-survey/src/auto_survey/line_reader.py`:
//! 1. osascript: activate LINE, navigate to community
//! 2. screencapture -l <CGWindowID>: capture LINE window
//! 3. sips --cropToHeightWidth: crop right-pane message area
//! 4. HTTP GET stations/ocr :10202/extract?engine=apple (Apple Vision, Swift binary)
//! 5. regex: extract SurveyCake URLs
//!
//! macOS-only. All subprocess calls are non-destructive read-only operations on the UI.

#![allow(dead_code)]

use anyhow::{anyhow, Result};
use regex::Regex;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::time::sleep;

use crate::config::Settings;
use crate::ocr_client;

// ---------------------------------------------------------------------------
// AppleScript constants — text MUST be character-for-character identical
// to the Python source (line_reader.py lines 29-79).
// ---------------------------------------------------------------------------

/// Static activation-only script (opens LINE and ensures chat window is visible).
/// Use `build_activate_script(community_name)` when community navigation is needed.
pub const SCRIPT_ACTIVATE: &str = r#"tell application "LINE" to activate
delay 1.5

tell application "System Events"
    tell process "LINE"
        if (count of windows) = 0 then
            click menu item "聊天" of menu "顯示" of menu bar 1
            delay 1.5
        end if
    end tell
end tell
"#;

/// Build a dynamic AppleScript that activates LINE, opens the 社群 tab,
/// searches for `community_name`, and navigates to it.
///
/// Mirrors Python `read_line_community()` flow:
///   1. activate LINE + ensure chat window visible
///   2. click 社群 tab (menu item)
///   3. keystroke community_name in search field
///   4. Return key to navigate
pub fn build_activate_script(community_name: &str) -> String {
    // Escape backslashes and double-quotes for embedding in AppleScript string literal
    let escaped = community_name.replace('\\', "\\\\").replace('"', "\\\"");
    format!(
        r#"tell application "LINE" to activate
delay 1.5

tell application "System Events"
    tell process "LINE"
        if (count of windows) = 0 then
            click menu item "聊天" of menu "顯示" of menu bar 1
            delay 1.5
        end if
        -- Navigate to 社群 tab
        try
            click menu item "社群" of menu "顯示" of menu bar 1
            delay 1.0
        end try
        -- Search for community by name
        try
            keystroke "f" using {{command down}}
            delay 0.5
            keystroke "{escaped}"
            delay 1.0
            key code 36
            delay 1.5
        end try
    end tell
end tell
"#,
        escaped = escaped
    )
}

pub const SCRIPT_ESCAPE: &str = r#"tell application "System Events"
    tell process "LINE"
        key code 53
        delay 0.2
        key code 53
        delay 0.2
    end tell
end tell
"#;

pub const SCRIPT_SCROLL_UP: &str = r#"tell application "System Events"
    tell process "LINE"
        key code 116
        delay 0.5
    end tell
end tell
"#;

// ---------------------------------------------------------------------------
// Regex for SurveyCake URLs (OCR may misread www as ww/vvw, http as htt, etc.)
// ---------------------------------------------------------------------------

fn surveycake_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"https?://w{2,3}\.surveycake\.com/s/\w+").expect("invalid regex")
    })
}

// ---------------------------------------------------------------------------
// osascript runner
// ---------------------------------------------------------------------------

fn run_osascript(script: &str, timeout_secs: u64) -> Option<String> {
    let result = Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output();

    match result {
        Ok(out) if out.status.success() => {
            Some(String::from_utf8_lossy(&out.stdout).trim().to_string())
        }
        Ok(out) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            tracing::debug!("osascript non-zero ({}): {}", out.status, stderr.trim());
            None
        }
        Err(e) => {
            tracing::debug!("osascript exec error: {}", e);
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Activate LINE and navigate to the community tab
// ---------------------------------------------------------------------------

/// Activate LINE and navigate to the specified community by name.
///
/// Mirrors Python `read_line_community()` steps 1-2:
/// 1. Activate LINE + ensure chat window visible
/// 2. Navigate to 社群 tab and search for `name`
pub fn activate_line_and_go_to_community(name: &str) -> bool {
    tracing::debug!("activating LINE for community '{}'", name);
    let script = build_activate_script(name);
    run_osascript(&script, 15).is_some()
}

// ---------------------------------------------------------------------------
// Get LINE's CGWindowID
// ---------------------------------------------------------------------------

/// Python one-liner that calls Quartz CGWindowListCopyWindowInfo to get the true
/// CGWindowNumber (kCGWindowNumber) required by `screencapture -l`.
/// This is the correct approach mirroring Python line_reader.py:107-118.
const PYTHON_GET_CG_WID: &str = r#"import Quartz,sys
ws=Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly|Quartz.kCGWindowListExcludeDesktopElements,Quartz.kCGNullWindowID)
for w in ws:
    if w.get('kCGWindowOwnerName')=='LINE' and w.get('kCGWindowName'):
        print(int(w['kCGWindowNumber']));sys.exit(0)
sys.exit(1)"#;

/// Get LINE's CGWindowID using Quartz via Python3 subprocess.
///
/// Uses `CGWindowListCopyWindowInfo` → `kCGWindowNumber` — the same approach
/// as Python `line_reader.py:_get_line_window_id()`. This is the correct
/// Quartz CGWindowID required by `screencapture -l <wid>`.
///
/// Falls back to `osascript do shell script` if the direct Python call fails.
pub fn get_line_window_id() -> Option<u32> {
    // Primary: Python3 + Quartz (pyobjc available on macOS)
    let result = Command::new("/usr/bin/python3")
        .args(["-c", PYTHON_GET_CG_WID])
        .output();

    if let Ok(out) = result {
        if out.status.success() {
            let stdout = String::from_utf8_lossy(&out.stdout);
            if let Some(wid) = stdout.trim().parse::<u32>().ok().filter(|&id| id > 0) {
                tracing::debug!("CGWindowID via Python3/Quartz: {}", wid);
                return Some(wid);
            }
        } else {
            tracing::debug!(
                "python3 CGWindowListCopyWindowInfo failed: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            );
        }
    }

    // Fallback: osascript do shell script wrapping the same Python snippet
    let osascript_fallback = format!(
        r#"do shell script "/usr/bin/python3 -c '{}'"#,
        PYTHON_GET_CG_WID.replace('\'', "\\'")
    );
    let out = run_osascript(&osascript_fallback, 10)?;
    out.trim().parse::<u32>().ok().filter(|&id| id > 0)
}

// ---------------------------------------------------------------------------
// Capture LINE window by CGWindowID
// ---------------------------------------------------------------------------

pub fn capture_line_window(wid: u32) -> Option<PathBuf> {
    let tmp = std::env::temp_dir().join(format!("line_cap_{}.png", wid));
    let result = Command::new("screencapture")
        .args(["-l", &wid.to_string(), "-o", tmp.to_str().unwrap_or("/tmp/line_cap.png")])
        .output();

    match result {
        Ok(out) if out.status.success() => {
            if tmp.exists() && tmp.metadata().map(|m| m.len()).unwrap_or(0) > 1000 {
                Some(tmp)
            } else {
                tracing::debug!("screencapture output too small or missing");
                let _ = std::fs::remove_file(&tmp);
                None
            }
        }
        Ok(out) => {
            tracing::debug!("screencapture failed: {}", String::from_utf8_lossy(&out.stderr).trim());
            None
        }
        Err(e) => {
            tracing::debug!("screencapture exec error: {}", e);
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Crop right-pane message area with sips
// ---------------------------------------------------------------------------

/// Returns (width, height) parsed from `sips -g pixelHeight -g pixelWidth` output.
fn sips_dimensions(src: &Path) -> Option<(u32, u32)> {
    let out = Command::new("sips")
        .args(["-g", "pixelHeight", "-g", "pixelWidth", src.to_str()?])
        .output()
        .ok()?;

    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut width = 0u32;
    let mut height = 0u32;
    for line in stdout.lines() {
        if line.contains("pixelHeight") {
            if let Some(val) = line.split(':').nth(1) {
                height = val.trim().parse().unwrap_or(0);
            }
        } else if line.contains("pixelWidth") {
            if let Some(val) = line.split(':').nth(1) {
                width = val.trim().parse().unwrap_or(0);
            }
        }
    }
    if width > 0 && height > 0 {
        Some((width, height))
    } else {
        None
    }
}

/// Compute crop parameters (pure function, testable without I/O).
///
/// Mirrors Python line_reader.py lines 159-163:
/// ```python
/// crop_x = int(width * 0.55)
/// crop_y = 95
/// crop_w = width - crop_x
/// crop_h = height - 140  # 95 top + 45 bottom
/// ```
pub fn crop_params(width: u32, height: u32) -> (u32, u32, u32, u32) {
    let crop_x = (width as f64 * 0.55) as u32;
    let crop_y: u32 = 95;
    let crop_w = width.saturating_sub(crop_x);
    let crop_h = height.saturating_sub(140);
    (crop_x, crop_y, crop_w, crop_h)
}

pub fn crop_message_area(src: &Path) -> Option<PathBuf> {
    let stem = src.file_stem()?.to_string_lossy();
    let dst = src.with_file_name(format!("{}_crop.png", stem));

    let (width, height) = sips_dimensions(src)?;

    if width < 400 || height < 300 {
        return None;
    }

    let (crop_x, crop_y, crop_w, crop_h) = crop_params(width, height);

    let status = Command::new("sips")
        .args([
            "--cropToHeightWidth",
            &crop_h.to_string(),
            &crop_w.to_string(),
            "--cropOffset",
            &crop_y.to_string(),
            &crop_x.to_string(),
            src.to_str()?,
            "--out",
            dst.to_str()?,
        ])
        .status()
        .ok()?;

    if status.success() && dst.exists() && dst.metadata().map(|m| m.len()).unwrap_or(0) > 500 {
        Some(dst)
    } else {
        let _ = std::fs::remove_file(&dst);
        None
    }
}

// ---------------------------------------------------------------------------
// URL extraction helpers
// ---------------------------------------------------------------------------

/// Extract SurveyCake URLs from raw OCR text.
pub fn extract_surveycake_urls(ocr_text: &str) -> Vec<String> {
    surveycake_re()
        .find_iter(ocr_text)
        .map(|m| m.as_str().to_string())
        .collect()
}

/// Extract structured `{attend_url, quiz_url}` from OCR text, with keyword heuristics.
///
/// Mirrors Python `extract_survey_urls()` in line_reader.py.
pub fn extract_survey_urls(text: &str) -> (Option<String>, Option<String>) {
    // Reassemble broken URLs caused by OCR line-breaks
    let mut merged: Vec<String> = Vec::new();
    // Note: `https?://` is intentionally excluded — a complete URL on its own line
    // should NOT be treated as a continuation fragment of the previous line.
    let url_continuation =
        Regex::new(r"^(w{2,3}\.|surveycake|[A-Za-z0-9]{3,8}$)").expect("regex");
    for line in text.lines() {
        let stripped = line.trim().to_string();
        if !merged.is_empty() && url_continuation.is_match(&stripped) {
            let last = merged.last_mut().unwrap();
            last.push_str(&stripped);
        } else {
            merged.push(stripped);
        }
    }
    let reassembled = merged.join("\n");

    let urls: Vec<String> = surveycake_re()
        .find_iter(&reassembled)
        .map(|m| m.as_str().to_string())
        .collect();

    if urls.is_empty() {
        return (None, None);
    }

    let mut attend_url: Option<String> = None;
    let mut quiz_url: Option<String> = None;

    let lines: Vec<&str> = reassembled.lines().collect();
    for (i, line) in lines.iter().enumerate() {
        if line.contains("簽到") {
            if let Some(m) = surveycake_re().find(line) {
                attend_url = Some(m.as_str().to_string());
            } else if let Some(next) = lines.get(i + 1) {
                if let Some(m) = surveycake_re().find(next) {
                    attend_url = Some(m.as_str().to_string());
                }
            }
        }
        if line.contains("測驗") {
            if let Some(m) = surveycake_re().find(line) {
                quiz_url = Some(m.as_str().to_string());
            } else if let Some(next) = lines.get(i + 1) {
                if let Some(m) = surveycake_re().find(next) {
                    quiz_url = Some(m.as_str().to_string());
                }
            }
        }
    }

    // Fallback: assign by order
    if attend_url.is_none() && quiz_url.is_none() {
        attend_url = urls.first().cloned();
        quiz_url = urls.get(1).cloned();
    }

    // Normalize OCR artifact: ww.surveycake → www.surveycake
    let fix = |u: Option<String>| {
        u.map(|s| {
            let ocr_fix = Regex::new(r"://ww\.surveycake").expect("regex");
            ocr_fix.replace(&s, "://www.surveycake").to_string()
        })
    };

    (fix(attend_url), fix(quiz_url))
}

// ---------------------------------------------------------------------------
// Main public API
// ---------------------------------------------------------------------------

/// Fetch the latest SurveyCake URLs from LINE community.
///
/// Flow: activate → (scroll_pages iterations of: scroll_up → capture → crop → OCR → regex)
/// Returns deduplicated URLs in the order found (older pages prepended).
pub async fn fetch_latest_survey_urls(
    cfg: &Settings,
    client: &reqwest::Client,
    scroll_pages: u32,
) -> Vec<String> {
    let name = &cfg.line_community_name;

    // Step 1: Activate LINE
    activate_line_and_go_to_community(name);

    // Step 2: Get LINE window ID
    let wid = match get_line_window_id() {
        Some(id) => id,
        None => {
            tracing::warn!("Cannot get LINE window ID");
            return vec![];
        }
    };

    let mut all_urls: Vec<String> = Vec::new();
    let ocr_langs = &["zh-Hant", "zh-Hans", "en"];

    for page in 0..scroll_pages.max(1) {
        if page > 0 {
            // Scroll up for subsequent pages
            run_osascript(SCRIPT_SCROLL_UP, 5);
            sleep(Duration::from_millis(500)).await;
        }

        let screenshot = match capture_line_window(wid) {
            Some(p) => p,
            None => {
                tracing::warn!("capture_line_window failed (page {})", page);
                continue;
            }
        };

        let src_for_ocr = match crop_message_area(&screenshot) {
            Some(cropped) => cropped,
            None => screenshot.clone(),
        };

        let ocr_text = match ocr_client::extract_text(client, &cfg.ocr_url, &src_for_ocr, ocr_langs).await {
            Ok(t) => t,
            Err(e) => {
                tracing::warn!("OCR failed (page {}): {}", page, e);
                String::new()
            }
        };

        // Cleanup temp files
        let _ = std::fs::remove_file(&screenshot);
        if src_for_ocr != screenshot {
            let _ = std::fs::remove_file(&src_for_ocr);
        }

        let page_urls = extract_surveycake_urls(&ocr_text);
        // Prepend older pages (scroll_up = older messages appear)
        let mut new_all = page_urls;
        new_all.extend(all_urls);
        all_urls = new_all;
    }

    // Dedup while preserving order
    let mut seen = std::collections::HashSet::new();
    all_urls.retain(|u| seen.insert(u.clone()));

    run_osascript(SCRIPT_ESCAPE, 5);

    all_urls
}
