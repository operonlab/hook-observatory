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

/// Path to the Swift-compiled helper that prints LINE's window info.
/// Source: `stations/auto-survey-rs/bin/src/get_cg_wid.swift`
/// Build:  `stations/auto-survey-rs/bin/build.sh`
fn get_cg_wid_binary() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("bin")
        .join("get_cg_wid")
}

/// LINE's on-screen window info, queried from `CGWindowListCopyWindowInfo`.
///
/// `(x, y, w, h)` are global logical points, matching what `cliclick` expects.
/// Using CGWindowBounds directly (rather than AppleScript `position of front
/// window`) is essential for multi-monitor stability: AppleScript's values go
/// stale after cross-screen drags, Space switches, and window resize events,
/// and can leak Space-local coords on external displays. CGWindowBounds is
/// snapshot-atomic and always in the global coordinate space.
#[derive(Debug, Clone, Copy)]
pub struct LineWindowInfo {
    pub wid: u32,
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// Get LINE's window info (wid + bounds) from the Swift helper.
///
/// Output format: `"<wid> <x> <y> <w> <h>"` — five whitespace-separated tokens.
pub fn get_line_window_info() -> Option<LineWindowInfo> {
    let binary = get_cg_wid_binary();
    let out = Command::new(&binary).arg("LINE").output().ok()?;

    if !out.status.success() {
        tracing::debug!(
            "get_cg_wid {:?} failed: status={} stderr={}",
            binary,
            out.status,
            String::from_utf8_lossy(&out.stderr).trim()
        );
        return None;
    }

    let stdout = String::from_utf8_lossy(&out.stdout);
    let tokens: Vec<&str> = stdout.split_whitespace().collect();
    if tokens.len() != 5 {
        tracing::debug!("get_cg_wid output unexpected: {:?}", stdout);
        return None;
    }

    let wid: u32 = tokens[0].parse().ok().filter(|&id| id > 0)?;
    let x: f64 = tokens[1].parse().ok()?;
    let y: f64 = tokens[2].parse().ok()?;
    let w: f64 = tokens[3].parse().ok()?;
    let h: f64 = tokens[4].parse().ok()?;

    if w <= 0.0 || h <= 0.0 {
        tracing::debug!("get_cg_wid returned zero-sized bounds: w={} h={}", w, h);
        return None;
    }

    let info = LineWindowInfo { wid, x, y, w, h };
    tracing::debug!(
        "LINE window info: wid={} bounds=({}, {}, {}, {})",
        info.wid, info.x, info.y, info.w, info.h
    );
    Some(info)
}

/// Get LINE's CGWindowID only. Compatibility wrapper over [`get_line_window_info`].
pub fn get_line_window_id() -> Option<u32> {
    get_line_window_info().map(|i| i.wid)
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

/// OCR artifact characters that commonly appear at line ends — typically
/// Apple Vision misreads the slug tail letter `l` or `I` as pipe `|`,
/// or adds trailing punctuation that isn't part of the URL.
fn strip_ocr_line_artifacts(line: &str) -> String {
    line.trim()
        .trim_end_matches(|c: char| matches!(c, '|' | '｜' | ' ' | '\t'))
        .to_string()
}

/// Extract SurveyCake URLs from raw OCR text.
///
/// Performs multi-line reassembly: OCR often splits a URL across 3 lines
/// (`https://`, `www.surveycake.com/s/`, `SLUG`). We join adjacent lines
/// when the following line starts with a URL continuation pattern (or is
/// a plausible slug). Trailing `|` artifacts are stripped before matching
/// because Apple Vision misreads the letter `l` as pipe.
pub fn extract_surveycake_urls(ocr_text: &str) -> Vec<String> {
    // PaddleOCR returns blocks in *spatial* order (top-to-bottom, left-to-right).
    // A single URL that wraps across two lines in a chat bubble therefore appears
    // as multiple blocks with unrelated chat-list / timestamp blocks interleaved
    // between them — e.g.
    //   [23] "簽到連結：https://"
    //   [24] "你大膽假設小心求證，並..."    ← chat list noise
    //   [25] "www.surveycake.com/s/"
    //   [26] "上午11:09"                    ← timestamp noise
    //   [27] "8ZKzl"
    //
    // The old reassembly only consulted the previous line, so a single noise
    // line broke the join. New strategy: drop anything that doesn't look like
    // part of a SurveyCake URL, then concatenate in order.
    let domain_re = Regex::new(r"^w{2,3}\.surveycake\.com/s/?$").expect("regex");
    let slug_re = Regex::new(r"^[A-Za-z0-9]{4,12}$").expect("regex");

    // Phase 1: keep only URL-shaped fragments, preserving input order.
    let mut frags: Vec<String> = Vec::new();
    for line in ocr_text.lines() {
        let s = strip_ocr_line_artifacts(line);
        if s.is_empty() {
            continue;
        }
        let keep = s.contains("surveycake.com/s/")
            || s.ends_with("https://")
            || s.ends_with("htps://") // common PaddleOCR typo
            || s.ends_with("https:/")
            || s.ends_with("htps:/")
            || s.ends_with("https:")
            || s.ends_with("htps:")
            || domain_re.is_match(&s)
            || slug_re.is_match(&s);
        if keep {
            frags.push(s);
        }
    }

    // Phase 2: concatenate when the tail of the previous fragment expects more.
    let mut merged: Vec<String> = Vec::new();
    for f in frags {
        let wants_more = merged
            .last()
            .map(|last| {
                last.ends_with("https://")
                    || last.ends_with("htps://")
                    || last.ends_with("https:/")
                    || last.ends_with("htps:/")
                    || last.ends_with("https:")
                    || last.ends_with("htps:")
                    || last.ends_with("surveycake.com/s/")
                    || last.ends_with('/')
            })
            .unwrap_or(false);
        if wants_more {
            merged.last_mut().unwrap().push_str(&f);
        } else {
            merged.push(f);
        }
    }

    // Normalize the common OCR typo `htps://` → `https://` so the final regex
    // (which requires the full `https?://` prefix) still matches.
    let reassembled = merged
        .join("\n")
        .replace("htps://", "https://")
        .replace("htps:/", "https://")
        .replace("htps:", "https:");

    surveycake_re()
        .find_iter(&reassembled)
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

/// Fetch SurveyCake URLs from LINE using the **search-by-URL** strategy.
///
/// Instead of scrolling through chat rooms, we paste `https://www.surveyca`
/// into LINE's left-side search box. LINE then:
///   1. Filters the left chat list to rooms containing that substring
///   2. Opens the most recent matching message in the right pane (automatic)
///   3. Displays N/N navigation arrows on the right pane
///
/// This is **dramatically more reliable** than scroll+cliclick navigation:
/// no community selection, no pagination, no coordinate guessing.
///
/// Flow:
///   1. Activate LINE + get CGWindowID
///   2. Save existing clipboard (restore at end)
///   3. OCR current window to locate left search box
///   4. cliclick search box → cmd+A, delete, cmd+V `https://www.surveyca`
///   5. screencapture + OCR entire window → regex for `surveycake.com/s/SLUG`
///   6. ESC to clear search, restore clipboard
///
/// Returns deduplicated SurveyCake URLs found in the currently visible message.
/// Note: OCR may misread slug characters (e.g. `8` → `B`). Caller should
/// HEAD-validate URLs before treating as authoritative.
pub async fn fetch_latest_survey_urls(
    cfg: &Settings,
    client: &reqwest::Client,
    _scroll_pages_unused: u32,
) -> Vec<String> {
    // --- Step 1: locate LINE window (background-friendly — no focus stealing) ---
    //
    // Intentionally no `tell application "LINE" to activate` here. The rest of
    // the flow works entirely with LINE in the background because:
    //   • screencapture -l <CGWindowID> reads the window server buffer directly
    //   • AXValue writes (Step 4) mutate the text field without needing focus
    //   • clipboard restore uses pbcopy stdin (no UI contact)
    // Effect: the user can keep typing in another app while the scheduled job
    // runs — verified on 2026-04-20 with LINE parked on a secondary display.
    let info = match get_line_window_info() {
        Some(i) => i,
        None => {
            // LINE isn't running or has no visible window. Use `launch`, not
            // `activate`, so we don't steal focus even in the cold-start case.
            tracing::info!("LINE not running, launching in background...");
            let _ = Command::new("osascript")
                .args(["-e", r#"tell application "LINE" to launch"#])
                .output();
            sleep(Duration::from_secs(3)).await;
            match get_line_window_info() {
                Some(i) => i,
                None => {
                    tracing::warn!("LINE launch failed — no visible window");
                    return vec![];
                }
            }
        }
    };
    let wid = info.wid;
    tracing::info!(
        "LINE window: wid={} bounds=({}, {}, {}, {})",
        info.wid, info.x, info.y, info.w, info.h
    );

    // --- Step 2: save current clipboard (restore at end) ---
    let saved_clip = Command::new("pbpaste")
        .output()
        .ok()
        .map(|o| o.stdout);

    // --- Step 3: locate search box via OCR ---
    let initial_shot = match capture_line_window(wid) {
        Some(p) => p,
        None => {
            tracing::warn!("initial screencapture failed");
            return vec![];
        }
    };
    let search_coord = find_search_box_coord(client, &cfg.ocr_url, &initial_shot, info).await;
    let (sx, sy) = match search_coord {
        Some(c) => c,
        None => {
            tracing::warn!("Cannot find search box coord — aborting");
            save_debug_artifact("search-box-not-found", Some(&initial_shot), "");
            let _ = std::fs::remove_file(&initial_shot);
            return vec![];
        }
    };
    let _ = std::fs::remove_file(&initial_shot);
    tracing::info!("search box at ({}, {})", sx, sy);

    // --- Step 4: directly set search field value via AXValue ---
    //
    // We use AppleScript `set value of text field 1 to ...` rather than
    // cliclick+cmd+V because the AXValue mutation is atomic and doesn't
    // depend on input-method state or frontmost-app timing. (cliclick+paste
    // works some of the time but is flaky when frontmost app switches
    // between bash and LINE between osascript calls.)
    let _ = (sx, sy); // (coord unused in this strategy; kept for debugging)
    let set_result = Command::new("osascript")
        .args([
            "-e", r#"tell application "System Events""#,
            "-e", r#"tell process "LINE""#,
            "-e", r#"tell front window"#,
            "-e", r#"tell splitter group 1"#,
            "-e", r#"set value of text field 1 to "https://www.surveyca""#,
            "-e", r#"end tell"#,
            "-e", r#"end tell"#,
            "-e", r#"end tell"#,
            "-e", r#"end tell"#,
        ])
        .output();
    if let Ok(out) = &set_result {
        if !out.status.success() {
            tracing::warn!(
                "set search value failed: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            );
            cleanup_line_search(saved_clip).await;
            return vec![];
        }
    }
    sleep(Duration::from_millis(1500)).await; // wait LINE to filter AND auto-open top match
    // Note: LINE automatically opens the most recent matching message in the
    // right pane after search filter populates. No row-click needed.

    // --- Step 5: screencapture + OCR + extract URLs ---
    let screenshot = match capture_line_window(wid) {
        Some(p) => p,
        None => {
            tracing::warn!("post-search screencapture failed");
            cleanup_line_search(saved_clip).await;
            return vec![];
        }
    };
    let ocr_langs = &["zh-Hant", "zh-Hans", "en"];

    // Primary engine: PaddleOCR. It reads LINE message bubbles far more
    // accurately than Apple Vision — the latter truncates or misreads
    // slug characters when URLs wrap at bubble boundaries (verified vs.
    // live 4/17 ground-truth: apple → 8ZKz/cMBo, paddle → 8ZKzl/dvMBo).
    // Slower (~22 s for one LINE window screenshot) but the flow has
    // budget: cronicle fires at 13:00 and survey submission window ends
    // at 14:00.
    let primary_engine = "paddle";
    let ocr_text = match ocr_client::extract_text_with_engine(
        client,
        &cfg.ocr_url,
        &screenshot,
        ocr_langs,
        primary_engine,
    )
    .await
    {
        Ok(t) => t,
        Err(e) => {
            tracing::warn!("primary OCR failed ({}): {}", primary_engine, e);
            String::new()
        }
    };
    let primary_urls = extract_surveycake_urls(&ocr_text);
    tracing::info!("{} OCR URLs: {:?}", primary_engine, primary_urls);

    // --- Step 5b: HEAD-validate each URL; if any invalid, retry with Claude Vision ---
    //
    // WARNING: `validate_surveycake_urls` only rules out slugs under 5 chars —
    // any `>=5 char` slug (including OCR misreads) gets HTTP 200 from SurveyCake.
    // Content-based validation is a separate follow-up (see save_debug_artifact
    // diagnostics). Brute-force suffix repair was prototyped and removed because
    // /s/8ZKz + any single char all return 200, so repairs land on random surveys.
    let valid_set = validate_surveycake_urls(client, &primary_urls).await;
    let all_invalid_count = primary_urls.len() - valid_set.len();
    let needs_fallback = !primary_urls.is_empty() && all_invalid_count > 0;

    let final_urls: Vec<String> = if needs_fallback {
        tracing::info!(
            "{}/{} {} URLs failed HEAD — falling back to claude engine",
            all_invalid_count,
            primary_urls.len(),
            primary_engine,
        );
        let claude_text = match ocr_client::extract_text_with_engine(
            client,
            &cfg.ocr_url,
            &screenshot,
            ocr_langs,
            "claude",
        )
        .await
        {
            Ok(t) => t,
            Err(e) => {
                tracing::warn!("claude OCR failed: {}", e);
                String::new()
            }
        };
        let claude_urls = extract_surveycake_urls(&claude_text);
        tracing::info!("claude OCR URLs: {:?}", claude_urls);
        // Prefer claude URLs that HEAD-validate; fill in with valid primary ones
        let claude_valid = validate_surveycake_urls(client, &claude_urls).await;
        let mut merged: Vec<String> = claude_urls
            .iter()
            .filter(|u| claude_valid.contains(*u))
            .cloned()
            .collect();
        for u in &primary_urls {
            if valid_set.contains(u) && !merged.contains(u) {
                merged.push(u.clone());
            }
        }
        // If nothing validated, prefer the primary list (paddle > claude on LINE)
        if merged.is_empty() && !primary_urls.is_empty() {
            primary_urls
        } else if merged.is_empty() {
            claude_urls
        } else {
            merged
        }
    } else {
        primary_urls
    };
    let _ = std::fs::remove_file(&screenshot);

    // --- Step 6: cleanup — clear search box, restore clipboard ---
    cleanup_line_search(saved_clip).await;

    // Dedup while preserving order
    let mut seen = std::collections::HashSet::new();
    let mut unique: Vec<String> = Vec::new();
    for u in final_urls {
        if seen.insert(u.clone()) {
            unique.push(u);
        }
    }
    unique
}

/// HEAD-validate each SurveyCake URL against the live service.
/// Returns the subset that responded with a successful HTTP status.
///
/// SurveyCake returns 200 for valid slugs and 404 for invalid slugs, so
/// this is a cheap OCR-accuracy gate before spending Claude Vision credits.
async fn validate_surveycake_urls(
    client: &reqwest::Client,
    urls: &[String],
) -> std::collections::HashSet<String> {
    let mut valid = std::collections::HashSet::new();
    for u in urls {
        let ok = match client
            .head(u)
            .timeout(Duration::from_secs(5))
            .send()
            .await
        {
            Ok(resp) => resp.status().is_success(),
            Err(e) => {
                tracing::debug!("HEAD {} failed: {}", u, e);
                false
            }
        };
        tracing::debug!("validate {} → {}", u, if ok { "VALID" } else { "invalid" });
        if ok {
            valid.insert(u.clone());
        }
    }
    valid
}

/// Find screen coordinates of LINE's left search box ("搜尋聊天和訊息").
///
/// Uses OCR to locate the "Q" icon or the placeholder text, then returns
/// absolute screen coordinates suitable for `cliclick c:X,Y`. Returns `None`
/// if the icon cannot be found (e.g. LINE UI changed drastically).
async fn find_search_box_coord(
    client: &reqwest::Client,
    ocr_base_url: &str,
    screenshot: &Path,
    info: LineWindowInfo,
) -> Option<(i32, i32)> {
    // Screenshot pixel dims come from sips → backing pixels.
    // The per-window scale is derived directly from CGWindowBounds width/height
    // (logical points) divided by the backing pixel width/height: that gives
    // points-per-pixel for *this* window on *this* display, which is correct
    // even after cross-screen drags or resize (when AppleScript bounds lag).
    let (img_w, img_h) = sips_dimensions(screenshot)?;

    // POST OCR
    let ocr_resp = client
        .post(format!(
            "{}/extract?engine=apple&languages=zh-Hant,zh-Hans,en&path={}",
            ocr_base_url.trim_end_matches('/'),
            urlencoding::encode(screenshot.to_str()?)
        ))
        .send()
        .await
        .ok()?;
    let body: serde_json::Value = ocr_resp.json().await.ok()?;
    let blocks = body.get("blocks")?.as_array()?;

    // Prefer the "搜尋聊天和訊息" placeholder if visible; fall back to lone "Q"
    let mut best: Option<(String, f64, f64, f64, f64)> = None;
    for b in blocks {
        let text = b.get("text")?.as_str().unwrap_or("");
        let x = b.get("x")?.as_f64().unwrap_or(0.0);
        let y = b.get("y")?.as_f64().unwrap_or(0.0);
        let w = b.get("width")?.as_f64().unwrap_or(0.0);
        let h = b.get("height")?.as_f64().unwrap_or(0.0);
        if text.contains("搜尋聊天") {
            best = Some((text.to_string(), x, y, w, h));
            break;
        }
        if text == "Q" && (best.is_none() || best.as_ref().map(|b| b.0 != "搜尋聊天和訊息").unwrap_or(true)) {
            // keep first "Q" as fallback
            if best.is_none() {
                best = Some((text.to_string(), x, y, w, h));
            }
        }
    }
    let (_, x, y, w, h) = best?;

    // Apple Vision Y: 0 = bottom, 1 = top. Convert to backing-pixel space first.
    let sx_img = x * img_w as f64 + w * img_w as f64 / 2.0;
    let sy_img = (1.0 - y - h) * img_h as f64 + h * img_h as f64 / 2.0;
    // Backing pixels → logical points: one scalar per axis, always ≤ 1.0.
    let scale_x = info.w / img_w as f64;
    let scale_y = info.h / img_h as f64;
    let sx = (info.x + sx_img * scale_x) as i32;
    let sy = (info.y + sy_img * scale_y) as i32;
    tracing::debug!(
        "search-box target: bbox=({:.3},{:.3},{:.3},{:.3}) img=({},{}) scale=({:.3},{:.3}) → screen=({},{})",
        x, y, w, h, img_w, img_h, scale_x, scale_y, sx, sy
    );
    Some((sx, sy))
}

/// Find coordinates of the first row matching the search (e.g. "微光早餐會").
///
/// Currently unused — LINE auto-opens the top match after `set value` on the
/// search field. Kept for potential future use if LINE behavior changes.
#[allow(dead_code)]
async fn find_first_matching_row_coord(
    client: &reqwest::Client,
    ocr_base_url: &str,
    screenshot: &Path,
    img_dims: Option<(u32, u32)>,
) -> Option<(i32, i32)> {
    // Window position
    let pos_script = r#"tell application "System Events"
    tell process "LINE"
        tell front window
            set p to position
            set s to size
            return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
        end tell
    end tell
end tell"#;
    let pos_out = Command::new("osascript")
        .args(["-e", pos_script])
        .output()
        .ok()?;
    let pos_str = String::from_utf8_lossy(&pos_out.stdout);
    let nums: Vec<i32> = pos_str
        .trim()
        .split(',')
        .filter_map(|s| s.trim().parse().ok())
        .collect();
    if nums.len() != 4 {
        return None;
    }
    let (win_x, win_y, win_w, win_h) = (nums[0], nums[1], nums[2], nums[3]);
    let (img_w, img_h) = img_dims?;

    // OCR
    let resp = client
        .post(format!(
            "{}/extract?engine=apple&languages=zh-Hant,zh-Hans,en&path={}",
            ocr_base_url.trim_end_matches('/'),
            urlencoding::encode(screenshot.to_str()?)
        ))
        .send()
        .await
        .ok()?;
    let body: serde_json::Value = resp.json().await.ok()?;
    let blocks = body.get("blocks")?.as_array()?;

    // Find "找到 N 則訊息" blocks — the first one is the top result
    // We click just above it (on the community-name row, which is 20-30px higher)
    for b in blocks {
        let text = b.get("text")?.as_str().unwrap_or("");
        if text.contains("找到") && text.contains("訊息") {
            let x = b.get("x")?.as_f64().unwrap_or(0.0);
            let y = b.get("y")?.as_f64().unwrap_or(0.0);
            let w = b.get("width")?.as_f64().unwrap_or(0.0);
            let h = b.get("height")?.as_f64().unwrap_or(0.0);
            let sx_img = x * img_w as f64 + w * img_w as f64 / 2.0;
            // Click ~20 screen px above (on the room name) to ensure hit
            let sy_img = (1.0 - y - h) * img_h as f64 + h * img_h as f64 / 2.0 - 20.0;
            let scale_x = win_w as f64 / img_w as f64;
            let scale_y = win_h as f64 / img_h as f64;
            let rx = (win_x as f64 + sx_img * scale_x) as i32;
            let ry = (win_y as f64 + sy_img * scale_y) as i32;
            return Some((rx, ry));
        }
    }
    None
}

/// Persist a screenshot + diagnostic text when a stage fails.
///
/// Copies the screenshot (if present) and writes the associated text into
/// `~/workshop/outputs/auto-survey/line-debug/<timestamp>-<stage>.{png,txt}`.
/// Always no-op-safe: errors are logged at debug level and swallowed.
///
/// Honours env `AUTO_SURVEY_DEBUG=1` for forced dumps on success too; the
/// caller decides whether to always dump or only on failure.
pub fn save_debug_artifact(stage: &str, screenshot: Option<&Path>, text: &str) {
    let dir = match std::env::var("HOME") {
        Ok(home) => std::path::PathBuf::from(home)
            .join("workshop")
            .join("outputs")
            .join("auto-survey")
            .join("line-debug"),
        Err(_) => return,
    };
    if let Err(e) = std::fs::create_dir_all(&dir) {
        tracing::debug!("debug artifact mkdir failed: {}", e);
        return;
    }
    let ts = chrono::Local::now().format("%Y%m%d-%H%M%S").to_string();
    let slug = format!("{}-{}", ts, stage);
    if let Some(src) = screenshot {
        if src.exists() {
            let dst = dir.join(format!("{}.png", slug));
            if let Err(e) = std::fs::copy(src, &dst) {
                tracing::debug!("debug artifact copy failed: {}", e);
            }
        }
    }
    if !text.is_empty() {
        let dst = dir.join(format!("{}.txt", slug));
        if let Err(e) = std::fs::write(&dst, text) {
            tracing::debug!("debug artifact write failed: {}", e);
        }
    }
}

/// Clean up LINE after a search: clear the search box via AXValue, then
/// restore the user's clipboard.
///
/// The previous implementation used `keystroke "a" using {command down}` +
/// `key code 51` (delete), which only works when LINE is the frontmost app —
/// and could destructively type into whatever window the user was actually
/// focused on. AXValue mutation targets the LINE text field directly, so
/// it's safe even when LINE sits in the background.
async fn cleanup_line_search(saved_clip: Option<Vec<u8>>) {
    let _ = Command::new("osascript")
        .args([
            "-e", r#"tell application "System Events""#,
            "-e", r#"tell process "LINE""#,
            "-e", r#"tell front window"#,
            "-e", r#"tell splitter group 1"#,
            "-e", r#"set value of text field 1 to """#,
            "-e", r#"end tell"#,
            "-e", r#"end tell"#,
            "-e", r#"end tell"#,
            "-e", r#"end tell"#,
        ])
        .output();
    sleep(Duration::from_millis(200)).await;

    // Restore clipboard (pbcopy stdin — no UI contact, no focus steal)
    if let Some(content) = saved_clip {
        if let Ok(mut child) = Command::new("pbcopy")
            .stdin(std::process::Stdio::piped())
            .spawn()
        {
            if let Some(stdin) = child.stdin.as_mut() {
                use std::io::Write;
                let _ = stdin.write_all(&content);
            }
            let _ = child.wait();
        }
    }
}
