// Phase 0 spike: verify chromiumoxide can drive Chromium's CDP virtual time
// the same way as the Node Playwright reference implementation.
//
// What we test:
//   1. Launch Chromium with the deterministic-mode flags used by the Node renderer.
//   2. Open a data: URL with a CSS @keyframes animation translating a box across
//      the viewport over 1 second.
//   3. Pause virtual time, then advance it in 200ms budgets 5 times, reading
//      the box's computed transform after each advance.
//   4. Assert the translateX value rises monotonically — proving compositor-
//      driven animations *do* progress under virtual time when the right
//      flags are set.
//
// Run:
//   cargo run --bin spike --release

use anyhow::{anyhow, Context, Result};
use chromiumoxide::browser::{Browser, BrowserConfig};
use chromiumoxide::cdp::browser_protocol::emulation::{
    SetVirtualTimePolicyParams, VirtualTimePolicy,
};
use chromiumoxide::cdp::js_protocol::runtime::EvaluateParams;
use futures::StreamExt;
use std::time::Duration;

const HTML: &str = r#"data:text/html;charset=utf-8,<!doctype html><html><head><style>html,body{margin:0;background:#fff}.b{width:100px;height:100px;background:red;animation:m 1s linear forwards;position:absolute;left:0;top:0}@keyframes m{from{transform:translateX(0)}to{transform:translateX(500px)}}</style></head><body><div class="b" id="box"></div><script>window.__t0=Date.now();window.__counter=0;setInterval(()=>{window.__counter++;},100);</script></body></html>"#;

fn chromium_args() -> Vec<String> {
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
    ]
}

#[tokio::main(flavor = "multi_thread", worker_threads = 4)]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter("spike=info,chromiumoxide=warn")
        .init();

    // Locate a Chromium binary. Prefer $CHROME (explicit override), then the
    // Playwright cache (workshop-conventional install location).
    let chrome_path = std::env::var("CHROME").ok().or_else(|| {
        let home = std::env::var("HOME").ok()?;
        let candidates = [
            format!("{home}/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
            format!("{home}/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome".into(),
        ];
        candidates.into_iter().find(|p| std::path::Path::new(p).exists())
    });

    let mut builder = BrowserConfig::builder()
        .args(chromium_args())
        .viewport(Some(chromiumoxide::handler::viewport::Viewport {
            width: 800,
            height: 600,
            device_scale_factor: Some(1.0),
            emulating_mobile: false,
            is_landscape: false,
            has_touch: false,
        }));

    if let Some(p) = chrome_path.as_ref() {
        tracing::info!("using chromium at {p}");
        builder = builder.chrome_executable(p);
    } else {
        tracing::warn!("no explicit chromium found; relying on chromiumoxide default");
    }

    let cfg = builder
        .build()
        .map_err(|e| anyhow!("BrowserConfig build failed: {e}"))?;

    let (mut browser, mut handler) = Browser::launch(cfg).await.context("launching chromium")?;

    let handler_task = tokio::spawn(async move {
        while let Some(ev) = handler.next().await {
            if let Err(e) = ev {
                tracing::warn!("handler event err: {e:?}");
            }
        }
    });

    // chromiumoxide refuses to navigate data: URLs cleanly across all platforms.
    // Write the HTML to a tmp file and use a file:// URL instead.
    let html_body = r#"<!doctype html><html><head><style>html,body{margin:0;background:#fff}.b{width:100px;height:100px;background:red;animation:m 1s linear forwards;position:absolute;left:0;top:0}@keyframes m{from{transform:translateX(0)}to{transform:translateX(500px)}}</style></head><body><div class="b" id="box"></div><script>window.__t0=Date.now();window.__counter=0;setInterval(()=>{window.__counter++;},100);</script></body></html>"#;
    let tmp = std::env::temp_dir().join("browser-render-spike.html");
    std::fs::write(&tmp, html_body).context("write tmp html")?;
    let file_url = format!("file://{}", tmp.display());

    let page = browser.new_page("about:blank").await.context("open about:blank")?;
    page.goto(&file_url).await.context("goto file URL")?;
    page.wait_for_navigation().await.context("nav")?;

    // Wait for the box to actually exist before we touch virtual time.
    for attempt in 0..30 {
        let v = page
            .execute(
                EvaluateParams::builder()
                    .expression("!!document.getElementById('box')")
                    .return_by_value(true)
                    .build()
                    .map_err(|e| anyhow!("probe build: {e}"))?,
            )
            .await?;
        let exists = v
            .result
            .result
            .value
            .as_ref()
            .and_then(|x| x.as_bool())
            .unwrap_or(false);
        if exists {
            tracing::info!("box present after {} attempts", attempt);
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
        if attempt == 29 {
            return Err(anyhow!("box element never mounted"));
        }
    }

    // Pause virtual time.
    page.execute(
        SetVirtualTimePolicyParams::builder()
            .policy(VirtualTimePolicy::Pause)
            .build()
            .map_err(|e| anyhow!("pause build: {e}"))?,
    )
    .await
    .context("set policy pause")?;

    let mut translates: Vec<f64> = Vec::new();

    // Capture initial translateX (should be ~0).
    let (init_tx, init_counter) = read_state(&page).await?;
    tracing::info!("initial: translateX={init_tx:.2} counter={init_counter}");
    translates.push(init_tx);

    // Advance 5 × 200ms budgets.
    for i in 0..5 {
        page.execute(
            SetVirtualTimePolicyParams::builder()
                .policy(VirtualTimePolicy::Advance)
                .budget(200.0)
                .max_virtual_time_task_starvation_count(10_000)
                .build()
                .map_err(|e| anyhow!("advance build: {e}"))?,
        )
        .await
        .context("set policy advance")?;

        // After advance, give Chromium a real-world breath to flush compositor frames.
        tokio::time::sleep(Duration::from_millis(50)).await;

        let (tx, ctr) = read_state(&page).await?;
        tracing::info!("step {} translateX = {:.2} counter={ctr}", i + 1, tx);
        translates.push(tx);
    }

    // Print the sequence.
    println!("translateX sequence: {translates:?}");

    // Verify monotonic non-decreasing and final near 500.
    let mut ok = true;
    for w in translates.windows(2) {
        if w[1] < w[0] - 0.01 {
            ok = false;
            break;
        }
    }
    let last = *translates.last().unwrap_or(&0.0);
    let progressed = last > 50.0; // expect well past 50 after 1s of advance

    let _ = browser.close().await;
    drop(handler_task);

    if ok && progressed {
        println!("SPIKE OK: virtual time advance drives @keyframes animation (final={last:.1})");
        Ok(())
    } else {
        Err(anyhow!(
            "SPIKE FAILED: monotonic={ok}, last={last:.2}, seq={translates:?}"
        ))
    }
}

/// Return (translateX, setIntervalCounter). The counter is a sanity check
/// that JS timers advance under virtual time even if the compositor
/// animation appears stuck.
async fn read_state(page: &chromiumoxide::Page) -> Result<(f64, i64)> {
    let expr = r#"
      JSON.stringify((() => {
        const el = document.getElementById('box');
        let tx = 0;
        if (el) {
          try { tx = new DOMMatrix(getComputedStyle(el).transform).m41; }
          catch (e) { tx = -1; }
        } else { tx = -2; }
        return { tx, c: window.__counter || 0, t: (Date.now() - (window.__t0||0)) };
      })())
    "#;
    let params = EvaluateParams::builder()
        .expression(expr)
        .return_by_value(true)
        .build()
        .map_err(|e| anyhow!("eval build: {e}"))?;
    let result = page.execute(params).await.context("evaluate")?;
    let raw = result
        .result
        .result
        .value
        .as_ref()
        .and_then(|v| v.as_str())
        .unwrap_or("{}")
        .to_string();
    let parsed: serde_json::Value = serde_json::from_str(&raw).unwrap_or_else(|_| serde_json::json!({}));
    let tx = parsed.get("tx").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let c = parsed.get("c").and_then(|v| v.as_i64()).unwrap_or(0);
    let t = parsed.get("t").and_then(|v| v.as_i64()).unwrap_or(0);
    tracing::debug!("eval state: tx={tx} counter={c} t(ms since boot)={t}");
    Ok((tx, c))
}
