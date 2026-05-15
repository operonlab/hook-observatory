//! Chromium launch flags for deterministic offline rendering.
//!
//! These flags MUST stay in sync with the Node renderer (`render-video.mjs`).
//! Without them, compositor-driven animations (CSS @keyframes / transitions)
//! refuse to advance under CDP `Emulation.setVirtualTimePolicy`.
//!
//! Validated by Phase 0 spike (`src/bin/spike.rs`).

/// Returns the deterministic Chromium flag set used for offline rendering.
///
/// Notes:
/// * `--no-sandbox` is required when running as the workshop launchctl user.
/// * `--mute-audio` keeps Chromium from grabbing the macOS audio device.
/// * `--hide-scrollbars` prevents the chrome-vertical scrollbar from
///   appearing in screenshots when the page accidentally overflows.
pub fn deterministic_args() -> Vec<String> {
    vec![
        "--deterministic-mode".into(),
        "--run-all-compositor-stages-before-draw".into(),
        "--disable-new-content-rendering-timeout".into(),
        "--disable-image-animation-resync".into(),
        "--enable-begin-frame-control".into(),
        "--font-render-hinting=none".into(),
        "--force-color-profile=srgb".into(),
        "--hide-scrollbars".into(),
        "--mute-audio".into(),
        "--no-sandbox".into(),
        "--disable-dev-shm-usage".into(),
        "--disable-background-networking".into(),
        "--disable-features=TranslateUI,BackForwardCache".into(),
    ]
}

/// Locates a Chromium binary on this host.
///
/// Resolution order:
/// 1. `$CHROME` env var (explicit override).
/// 2. Playwright cache (`~/Library/Caches/ms-playwright/chromium-*/...`).
/// 3. macOS system Google Chrome.
/// 4. Linux/CI common paths.
pub fn find_chrome() -> Option<String> {
    if let Ok(p) = std::env::var("CHROME") {
        if std::path::Path::new(&p).exists() {
            return Some(p);
        }
    }
    let home = std::env::var("HOME").ok()?;
    let candidates = [
        // Playwright cache — workshop convention. Try newest revisions first.
        format!("{home}/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        format!("{home}/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        format!("{home}/Library/Caches/ms-playwright/chromium-1211/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        // System Chrome
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome".into(),
        // Linux
        "/usr/bin/google-chrome".into(),
        "/usr/bin/chromium-browser".into(),
        "/usr/bin/chromium".into(),
    ];
    candidates.into_iter().find(|p| std::path::Path::new(p).exists())
}
