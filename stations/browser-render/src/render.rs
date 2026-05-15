//! Core renderer — CDP virtual-time-driven frame capture.
//!
//! Algorithm (mirrors `~/.claude/skills/web-video-tutorial/templates/scripts/render-video.mjs`):
//!
//! 1. Launch Chromium with deterministic flags (see [`crate::flags`]).
//! 2. Navigate to `{url}/?render=1&chapter={N}&start={step}`, wait for
//!    `window.__renderState !== undefined && document.fonts.status === 'loaded'`.
//! 3. `Emulation.setVirtualTimePolicy { policy: "pause" }` — freeze the page.
//! 4. For each segment in the plan:
//!    a. Poll `window.__renderState.chapterId === seg.chapter_id && step === seg.step`
//!       (driven by `useAudioPlayer` setTimeouts under virtual time from the
//!       *previous* segment's tail-advance).
//!    b. Capture `seg.frame_count` frames, advancing virtual time by
//!       `1000/fps` ms between each.
//!    c. Tail-advance by `max(0, dur_ms - (frame_count-1)*ms_per_frame) + 100`
//!       so the next-step setTimeout fires.
//!
//! WHY `advance` not `pauseIfNetworkFetchesPending`: Vite dev server holds
//! a persistent HMR WebSocket which `pauseIfNetworkFetchesPending` will
//! wait on forever. `advance` policy ignores network state.

use anyhow::{anyhow, Context, Result};
use base64::Engine;
use chromiumoxide::browser::{Browser, BrowserConfig};
use chromiumoxide::cdp::browser_protocol::emulation::{
    SetVirtualTimePolicyParams, VirtualTimePolicy,
};
use chromiumoxide::cdp::browser_protocol::page::{
    CaptureScreenshotFormat, CaptureScreenshotParams,
};
use chromiumoxide::cdp::js_protocol::runtime::EvaluateParams;
use chromiumoxide::Page;
use futures::StreamExt;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::flags;
use crate::manifest::{build_plan, Format, Manifest, Segment, Viewport};

/// Public render request — also the HTTP `POST /render` body schema.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderRequest {
    pub url: String,
    /// Chapter id → list of step durations (ms). Order matters; iteration
    /// order of `BTreeMap` is alphabetical so callers wanting custom order
    /// must encode it in chapter IDs (e.g., `"00_intro"`, `"01_body"`).
    pub durations: BTreeMap<String, Vec<u64>>,
    pub out_dir: PathBuf,
    #[serde(default = "default_fps")]
    pub fps: u32,
    #[serde(default = "default_viewport")]
    pub viewport: [u32; 2], // [width, height]
    #[serde(default = "default_format")]
    pub format: Format,
    /// JPEG quality 1-100 (only used when format=jpeg).
    #[serde(default = "default_quality")]
    pub quality: u32,
    /// Render only this chapter (0-indexed). Frame indices remain global.
    #[serde(default)]
    pub chapter: Option<usize>,
}

fn default_fps() -> u32 { 30 }
fn default_viewport() -> [u32; 2] { [1920, 1080] }
fn default_format() -> Format { Format::Png }
fn default_quality() -> u32 { 90 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderResult {
    pub frames_dir: PathBuf,
    pub manifest_path: PathBuf,
    pub total_frames: usize,
    pub captured_segments: usize,
    pub wall_clock_seconds: f64,
}

/// Render a URL to a directory of frames + manifest.json.
pub async fn render(req: RenderRequest) -> Result<RenderResult> {
    let viewport = Viewport {
        width: req.viewport[0],
        height: req.viewport[1],
    };
    let (full_plan, total_frames) = build_plan(&req.durations, req.fps);
    if full_plan.is_empty() {
        return Err(anyhow!("durations is empty — no segments to render"));
    }

    let plan: Vec<Segment> = match req.chapter {
        Some(idx) => full_plan
            .iter()
            .filter(|s| s.chapter_idx == idx)
            .cloned()
            .collect(),
        None => full_plan.clone(),
    };
    if plan.is_empty() {
        return Err(anyhow!(
            "chapter={} produced zero segments (max idx in plan = {})",
            req.chapter.unwrap_or(usize::MAX),
            full_plan.iter().map(|s| s.chapter_idx).max().unwrap_or(0),
        ));
    }

    std::fs::create_dir_all(&req.out_dir).context("create out_dir")?;

    let started = std::time::Instant::now();

    // ── launch chromium ─────────────────────────────────────────────
    // Per-request user-data-dir so multiple concurrent renders do not
    // collide on Chromium's singleton lock.
    let user_data_dir = std::env::temp_dir().join(format!(
        "browser-render-{}",
        uuid_like_suffix()
    ));
    std::fs::create_dir_all(&user_data_dir).ok();

    let mut builder = BrowserConfig::builder()
        .args(flags::deterministic_args())
        .user_data_dir(&user_data_dir)
        .viewport(Some(chromiumoxide::handler::viewport::Viewport {
            width: viewport.width,
            height: viewport.height,
            device_scale_factor: Some(1.0),
            emulating_mobile: false,
            is_landscape: false,
            has_touch: false,
        }));
    if let Some(p) = flags::find_chrome() {
        tracing::info!("using chromium at {p}");
        builder = builder.chrome_executable(p);
    }
    let cfg = builder
        .build()
        .map_err(|e| anyhow!("BrowserConfig build: {e}"))?;
    let (mut browser, mut handler) = Browser::launch(cfg).await.context("launching chromium")?;
    let handler_task = tokio::spawn(async move {
        while let Some(ev) = handler.next().await {
            if let Err(e) = ev {
                tracing::trace!("handler ev: {e:?}");
            }
        }
    });

    let result = render_inner(&mut browser, &req, viewport, &plan, &full_plan, total_frames).await;

    let _ = browser.close().await;
    handler_task.abort();
    // Best-effort cleanup of the per-request user-data-dir.
    let _ = std::fs::remove_dir_all(&user_data_dir);

    let res = result?;
    let wall = started.elapsed().as_secs_f64();
    let manifest = Manifest {
        fps: req.fps,
        format: req.format,
        total_frames,
        viewport,
        segments: full_plan,
    };
    let manifest_path = req.out_dir.join("manifest.json");
    std::fs::write(
        &manifest_path,
        serde_json::to_vec_pretty(&manifest).context("serialize manifest")?,
    )
    .context("write manifest")?;
    tracing::info!(?manifest_path, "manifest written");

    Ok(RenderResult {
        frames_dir: req.out_dir.clone(),
        manifest_path,
        total_frames,
        captured_segments: res.captured_segments,
        wall_clock_seconds: wall,
    })
}

struct RenderProgress {
    captured_segments: usize,
}

async fn render_inner(
    browser: &mut Browser,
    req: &RenderRequest,
    _viewport: Viewport,
    plan: &[Segment],
    _full_plan: &[Segment],
    total_frames: usize,
) -> Result<RenderProgress> {
    let first = &plan[0];
    let nav_url = format!(
        "{}{}render=1&fps={}&chapter={}&start={}",
        req.url,
        if req.url.contains('?') { "&" } else { "?" },
        req.fps,
        first.chapter_idx,
        first.step,
    );
    tracing::info!(url = %nav_url, "navigating");

    let page = browser
        .new_page("about:blank")
        .await
        .context("open about:blank")?;

    // Trace setTimeout to help diagnose step-advance hangs (same as Node).
    let init_script = r#"
      window.__trace = { set: [], fired: [] };
      (function () {
        const orig = window.setTimeout;
        window.setTimeout = function (fn, ms, ...args) {
          window.__trace.set.push({ at: performance.now(), ms });
          const wrapped = function () {
            window.__trace.fired.push({ at: performance.now() });
            return fn.apply(this, arguments);
          };
          return orig(wrapped, ms, ...args);
        };
      })();
    "#;
    let _ = page
        .execute(
            chromiumoxide::cdp::browser_protocol::page::AddScriptToEvaluateOnNewDocumentParams::builder()
                .source(init_script)
                .build()
                .map_err(|e| anyhow!("init script build: {e}"))?,
        )
        .await;

    page.goto(&nav_url).await.context("goto target URL")?;
    page.wait_for_navigation().await.context("wait_for_navigation")?;

    // Wait for React mount + fonts (under wall-clock — bounded).
    wait_until(
        &page,
        "window.__renderState !== undefined && document.fonts.status === 'loaded'",
        Duration::from_secs(8),
    )
    .await
    .context("React mount + fonts ready")?;
    tracing::info!("React mounted + fonts ready");

    // Pause virtual time.
    page.execute(
        SetVirtualTimePolicyParams::builder()
            .policy(VirtualTimePolicy::Pause)
            .build()
            .map_err(|e| anyhow!("pause build: {e}"))?,
    )
    .await
    .context("setVirtualTimePolicy pause")?;
    tracing::info!("virtual time paused; capturing {} segments", plan.len());

    let pad_len = total_frames.to_string().len();
    let ms_per_frame = 1000.0_f64 / req.fps as f64;
    let mut captured_segments = 0;

    for (i, seg) in plan.iter().enumerate() {
        // Wait until __renderState matches this segment.
        let chid = seg.chapter_id.clone();
        let st = seg.step;
        let cond = format!(
            r#"(() => {{
              const r = window.__renderState;
              return !!r && r.chapterId === {chid:?} && r.step === {st};
            }})()"#
        );
        if let Err(e) = wait_until(&page, &cond, Duration::from_secs(8)).await {
            let dbg = read_debug(&page).await.unwrap_or_else(|err| format!("(debug failed: {err})"));
            return Err(anyhow!(
                "waitForFunction failed at segment {i} (ch={}, step={}): {e}\nPage state: {dbg}",
                seg.chapter_id, seg.step,
            ));
        }

        // Capture seg.frame_count frames, advancing ms_per_frame between each.
        for f in 0..seg.frame_count {
            if f > 0 {
                advance_ms(&page, ms_per_frame).await?;
            }
            let abs_frame = seg.start_frame + f;
            let name = format!(
                "{:0width$}.{ext}",
                abs_frame,
                width = pad_len,
                ext = req.format.ext()
            );
            let path = req.out_dir.join(&name);
            capture_frame(&page, &path, req.format, req.quality).await?;
        }

        // Tail-advance so the next-step setTimeout fires.
        let advanced_in_step = (seg.frame_count.saturating_sub(1)) as f64 * ms_per_frame;
        let tail = (seg.dur_ms as f64 - advanced_in_step).max(0.0) + 100.0;
        if tail > 0.0 {
            advance_ms(&page, tail).await?;
        }

        captured_segments += 1;
        tracing::info!(
            "ch{}/step{}: {} frames ({}ms) [{}..{}] {}/{}",
            seg.chapter_idx,
            seg.step,
            seg.frame_count,
            seg.dur_ms,
            seg.start_frame,
            seg.end_frame,
            seg.end_frame + 1,
            total_frames,
        );
    }

    Ok(RenderProgress { captured_segments })
}

async fn advance_ms(page: &Page, ms: f64) -> Result<()> {
    page.execute(
        SetVirtualTimePolicyParams::builder()
            .policy(VirtualTimePolicy::Advance)
            .budget(ms)
            .max_virtual_time_task_starvation_count(10_000)
            .build()
            .map_err(|e| anyhow!("advance build: {e}"))?,
    )
    .await
    .context("setVirtualTimePolicy advance")?;
    Ok(())
}

async fn capture_frame(page: &Page, path: &Path, format: Format, quality: u32) -> Result<()> {
    // Per-call CDP timeout. chromiumoxide's default execute() can hang
    // indefinitely on slow PNG encodes once we've accumulated 10+ 1080p
    // frames. Wrap each call in tokio::time::timeout with one retry so a
    // single slow frame doesn't crash the whole render job.
    const CDP_TIMEOUT: Duration = Duration::from_secs(60);

    let build = || {
        let mut b = CaptureScreenshotParams::builder()
            .format(match format {
                Format::Png => CaptureScreenshotFormat::Png,
                Format::Jpeg => CaptureScreenshotFormat::Jpeg,
            })
            .capture_beyond_viewport(false);
        if matches!(format, Format::Jpeg) {
            b = b.quality(quality as i64);
        }
        b.build()
    };

    let resp = match tokio::time::timeout(CDP_TIMEOUT, page.execute(build())).await {
        Ok(r) => r.context("captureScreenshot")?,
        Err(_) => {
            tracing::warn!(
                "captureScreenshot timed out after {:?}, retrying once",
                CDP_TIMEOUT
            );
            tokio::time::timeout(CDP_TIMEOUT, page.execute(build()))
                .await
                .map_err(|_| anyhow!("captureScreenshot timed out twice"))?
                .context("captureScreenshot retry")?
        }
    };
    let b64: &str = resp.result.data.as_ref();
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .context("decode screenshot base64")?;
    tokio::fs::write(path, bytes)
        .await
        .with_context(|| format!("write frame {path:?}"))?;
    Ok(())
}

async fn wait_until(page: &Page, expr: &str, timeout: Duration) -> Result<()> {
    let deadline = std::time::Instant::now() + timeout;
    let mut tries = 0u32;
    loop {
        let params = EvaluateParams::builder()
            .expression(expr)
            .return_by_value(true)
            .build()
            .map_err(|e| anyhow!("eval build: {e}"))?;
        let result = page.execute(params).await.context("evaluate")?;
        let ok = result
            .result
            .result
            .value
            .as_ref()
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if ok {
            return Ok(());
        }
        tries += 1;
        if std::time::Instant::now() >= deadline {
            return Err(anyhow!(
                "wait_until timed out after {tries} polls: `{expr}`"
            ));
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

/// Cheap, collision-resistant suffix for per-request user-data-dir.
/// Combines pid + nanos + a process-local counter — avoids pulling in uuid.
fn uuid_like_suffix() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static CTR: AtomicU64 = AtomicU64::new(0);
    let n = CTR.fetch_add(1, Ordering::Relaxed);
    let pid = std::process::id();
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{pid}-{nanos}-{n}")
}

async fn read_debug(page: &Page) -> Result<String> {
    let expr = r#"JSON.stringify({
      renderState: window.__renderState,
      trace: window.__trace && {
        set: (window.__trace.set || []).slice(0, 20),
        fired: (window.__trace.fired || []).slice(0, 20),
        setCount: (window.__trace.set || []).length,
        firedCount: (window.__trace.fired || []).length,
      },
      now: performance.now(),
    })"#;
    let params = EvaluateParams::builder()
        .expression(expr)
        .return_by_value(true)
        .build()
        .map_err(|e| anyhow!("debug eval build: {e}"))?;
    let result = page.execute(params).await.context("debug evaluate")?;
    Ok(result
        .result
        .result
        .value
        .as_ref()
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| "(none)".into()))
}
