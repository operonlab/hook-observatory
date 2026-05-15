//! Smoke test: drive the renderer against a self-hosted minimal HTML page
//! and assert manifest / frame counts / pixel diff.

use std::collections::BTreeMap;
use std::net::SocketAddr;
use std::path::PathBuf;

use axum::{response::Html, routing::get, Router};
use browser_render::manifest::{Format, Manifest};
use browser_render::render::{render, RenderRequest};

const TEST_PAGE: &str = r##"<!doctype html>
<html><head>
<style>
  html, body { margin: 0; background: #fff; }
  .box {
    width: 100px; height: 100px; background: red;
    position: absolute; left: 0; top: 0;
    animation: m 1s linear forwards;
  }
  @keyframes m { from { transform: translateX(0); } to { transform: translateX(800px); } }
</style>
</head><body>
<div class="box" id="box"></div>
<script>
  // Minimal contract: expose __renderState and auto-advance step on a timer.
  // step holds for 500 ms then advances; 2 steps in chapter "intro".
  window.__renderState = { chapter: 0, step: 0, chapterId: "intro", globalIndex: 0, totalGlobal: 2, stepDurationMs: 500, done: false };
  const params = new URLSearchParams(location.search);
  const startStep = parseInt(params.get('start') || '0', 10);
  window.__renderState.step = startStep;
  function tick() {
    if (window.__renderState.step >= 1) {
      window.__renderState.done = true;
      return;
    }
    setTimeout(() => {
      window.__renderState.step += 1;
      window.__renderState.globalIndex += 1;
      tick();
    }, 500);
  }
  tick();
</script>
</body></html>"##;

async fn run_test_server() -> (SocketAddr, tokio::task::JoinHandle<()>) {
    let app = Router::new().route("/", get(|| async { Html(TEST_PAGE) }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let handle = tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });
    (addr, handle)
}

fn skip_if_no_chrome() -> bool {
    browser_render::flags::find_chrome().is_none()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn smoke_render_two_steps() {
    if skip_if_no_chrome() {
        eprintln!("SKIP: no Chromium binary found via flags::find_chrome");
        return;
    }

    let (addr, _server) = run_test_server().await;
    let url = format!("http://{}/", addr);

    let tmp = tempfile::tempdir().unwrap();
    let out_dir: PathBuf = tmp.path().to_path_buf();

    let mut durations = BTreeMap::new();
    durations.insert("intro".to_string(), vec![500u64, 500u64]);

    let req = RenderRequest {
        url: url.clone(),
        durations,
        out_dir: out_dir.clone(),
        fps: 10,
        viewport: [400, 200],
        format: Format::Png,
        quality: 90,
        chapter: None,
    };

    let res = render(req).await.expect("render should succeed");

    // 500ms × 10fps = 5 frames per step × 2 steps = 10 total frames
    assert_eq!(res.total_frames, 10, "total_frames mismatch");
    assert_eq!(res.captured_segments, 2, "captured 2 segments");

    let manifest_bytes = std::fs::read(&res.manifest_path).unwrap();
    let m: Manifest = serde_json::from_slice(&manifest_bytes).unwrap();
    assert_eq!(m.fps, 10);
    assert!(matches!(m.format, Format::Png));
    assert_eq!(m.total_frames, 10);
    assert_eq!(m.segments.len(), 2);
    assert_eq!(m.segments[0].chapter_id, "intro");
    assert_eq!(m.segments[0].step, 0);
    assert_eq!(m.segments[0].frame_count, 5);
    assert_eq!(m.segments[0].start_frame, 0);
    assert_eq!(m.segments[0].end_frame, 4);
    assert_eq!(m.segments[1].step, 1);
    assert_eq!(m.segments[1].start_frame, 5);
    assert_eq!(m.segments[1].end_frame, 9);

    // Frames written?
    let n_frames = std::fs::read_dir(&out_dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.path()
                .extension()
                .and_then(|s| s.to_str())
                .map(|s| s == "png")
                .unwrap_or(false)
        })
        .count();
    assert_eq!(n_frames, 10, "expected 10 PNG frames on disk");

    // Frame 0 (animation just starting) ≠ frame 9 (animation done) — pixel diff.
    let pad_len = res.total_frames.to_string().len();
    let f0 = out_dir.join(format!("{:0w$}.png", 0, w = pad_len));
    let f9 = out_dir.join(format!("{:0w$}.png", 9, w = pad_len));
    let b0 = std::fs::read(&f0).expect("frame 0");
    let b9 = std::fs::read(&f9).expect("frame 9");
    assert_ne!(b0, b9, "frame 0 and frame 9 should differ (animation moved)");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn smoke_render_specific_chapter() {
    if skip_if_no_chrome() {
        eprintln!("SKIP: no Chromium binary found");
        return;
    }

    let (addr, _server) = run_test_server().await;
    let url = format!("http://{}/", addr);

    let tmp = tempfile::tempdir().unwrap();
    let out_dir: PathBuf = tmp.path().to_path_buf();

    let mut durations = BTreeMap::new();
    durations.insert("intro".to_string(), vec![500u64, 500u64]);

    let req = RenderRequest {
        url,
        durations,
        out_dir: out_dir.clone(),
        fps: 10,
        viewport: [400, 200],
        format: Format::Png,
        quality: 90,
        chapter: Some(0),
    };

    let res = render(req).await.expect("render should succeed");
    // Even with chapter filter, total_frames in manifest is the FULL plan.
    assert_eq!(res.total_frames, 10);
    assert_eq!(res.captured_segments, 2);

    let m: Manifest = serde_json::from_slice(&std::fs::read(&res.manifest_path).unwrap()).unwrap();
    assert_eq!(m.segments.len(), 2, "manifest always describes FULL plan");
}
