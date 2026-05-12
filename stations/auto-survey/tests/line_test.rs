//! Tests for line.rs — pure-function tests only, no osascript/LINE side effects.
//!
//! - URL regex extraction from fake OCR text
//! - crop_params() dimension calculation (pure function)
//! - extract_survey_urls() keyword heuristics

use auto_survey::line::{crop_params, extract_surveycake_urls, extract_survey_urls};

// ---------------------------------------------------------------------------
// 1. Regex URL extraction
// ---------------------------------------------------------------------------

#[test]
fn test_extract_urls_basic() {
    let text = "今日測驗 https://www.surveycake.com/s/AbCd12\n今日簽到 http://www.surveycake.com/s/XyZ99";
    let urls = extract_surveycake_urls(text);
    assert_eq!(urls.len(), 2);
    assert!(urls[0].contains("AbCd12"));
    assert!(urls[1].contains("XyZ99"));
}

#[test]
fn test_extract_urls_ocr_ww_variant() {
    // OCR may misread www as ww
    let text = "http://ww.surveycake.com/s/Test01";
    let urls = extract_surveycake_urls(text);
    assert_eq!(urls.len(), 1, "should match ww variant");
}

#[test]
fn test_extract_urls_empty() {
    let text = "沒有任何連結在這裡";
    let urls = extract_surveycake_urls(text);
    assert!(urls.is_empty());
}

#[test]
fn test_extract_urls_deduplication_is_not_done_here() {
    // extract_surveycake_urls returns all matches (caller deduplicates)
    let text = "https://www.surveycake.com/s/abc\nhttps://www.surveycake.com/s/abc";
    let urls = extract_surveycake_urls(text);
    assert_eq!(urls.len(), 2); // raw finds, not deduped
}

// ---------------------------------------------------------------------------
// 2. crop_params() — pure dimension calculation
// ---------------------------------------------------------------------------

#[test]
fn test_crop_params_standard_window() {
    // Typical LINE window: 1200 x 800
    let (crop_x, crop_y, crop_w, crop_h) = crop_params(1200, 800);
    assert_eq!(crop_x, 660);   // 1200 * 0.55 = 660
    assert_eq!(crop_y, 95);
    assert_eq!(crop_w, 540);   // 1200 - 660 = 540
    assert_eq!(crop_h, 660);   // 800 - 140 = 660
}

#[test]
fn test_crop_params_retina_window() {
    // Retina doubled: 2400 x 1600
    let (crop_x, crop_y, crop_w, crop_h) = crop_params(2400, 1600);
    assert_eq!(crop_x, 1320);  // 2400 * 0.55 = 1320
    assert_eq!(crop_y, 95);
    assert_eq!(crop_w, 1080);  // 2400 - 1320 = 1080
    assert_eq!(crop_h, 1460);  // 1600 - 140 = 1460
}

#[test]
fn test_crop_params_minimum_no_underflow() {
    // Height just barely above 140 — should not underflow
    let (_, _, crop_w, crop_h) = crop_params(500, 150);
    assert_eq!(crop_h, 10); // 150 - 140 = 10
    assert!(crop_w > 0);
}

// ---------------------------------------------------------------------------
// 3. extract_survey_urls() — keyword heuristics
// ---------------------------------------------------------------------------

#[test]
fn test_extract_survey_urls_keyword_match() {
    let text = "簽到連結: https://www.surveycake.com/s/ATTEND1\n測驗連結: https://www.surveycake.com/s/QUIZ99";
    let (attend, quiz) = extract_survey_urls(text);
    assert_eq!(attend.unwrap(), "https://www.surveycake.com/s/ATTEND1");
    assert_eq!(quiz.unwrap(), "https://www.surveycake.com/s/QUIZ99");
}

#[test]
fn test_extract_survey_urls_fallback_order() {
    // No keywords — fallback assigns first=attend, second=quiz
    let text = "https://www.surveycake.com/s/First\nhttps://www.surveycake.com/s/Second";
    let (attend, quiz) = extract_survey_urls(text);
    assert_eq!(attend.unwrap(), "https://www.surveycake.com/s/First");
    assert_eq!(quiz.unwrap(), "https://www.surveycake.com/s/Second");
}

#[test]
fn test_extract_survey_urls_ocr_ww_normalization() {
    // ww.surveycake → www.surveycake after normalization
    let text = "簽到 http://ww.surveycake.com/s/abc";
    let (attend, quiz) = extract_survey_urls(text);
    // ww.surveycake doesn't match www in regex, but normalization applies post-match
    // (ww matches w{2,3} so it IS captured)
    assert!(attend.map(|u| u.contains("www.surveycake")).unwrap_or(false), "should normalize ww→www");
    assert!(quiz.is_none());
}

#[test]
fn test_extract_survey_urls_no_urls() {
    let text = "只有文字，沒有連結";
    let (attend, quiz) = extract_survey_urls(text);
    assert!(attend.is_none());
    assert!(quiz.is_none());
}

// ---------------------------------------------------------------------------
// 4. AppleScript const sanity checks (字元層級驗證)
// ---------------------------------------------------------------------------

#[test]
fn test_applescript_activate_contains_key_lines() {
    // Verify SCRIPT_ACTIVATE contains required AppleScript phrases
    let script = auto_survey::line::SCRIPT_ACTIVATE;
    assert!(script.contains(r#"tell application "LINE" to activate"#));
    assert!(script.contains("delay 1.5"));
    assert!(script.contains("聊天"));
    assert!(script.contains("顯示"));
}

#[test]
fn test_applescript_escape_key_code_53() {
    let script = auto_survey::line::SCRIPT_ESCAPE;
    // Escape key is key code 53
    assert_eq!(script.matches("key code 53").count(), 2);
    assert_eq!(script.matches("delay 0.2").count(), 2);
}

#[test]
fn test_applescript_scroll_up_key_code_116() {
    let script = auto_survey::line::SCRIPT_SCROLL_UP;
    // Page Up key is key code 116
    assert!(script.contains("key code 116"));
    assert!(script.contains("delay 0.5"));
}
