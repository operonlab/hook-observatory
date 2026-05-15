# browser-render

Workshop's offline web → frames renderer. Drives a running web app through
Chrome DevTools Protocol (CDP) `Emulation.setVirtualTimePolicy` to capture
deterministic, frame-perfect screenshots independent of wall-clock.

**Stack**: Rust + axum + chromiumoxide (CDP-native, no Playwright runtime).

**Port**: `10221` (range `10200-10299` — AI & Media stations).

---

## When to use

Any web app that wants to render a video offline (faster-than-wall-clock,
frame-accurate) should target this station. The downstream skill
(`web-video-tutorial`, future `ideagraph-editor`, etc.) only needs to
satisfy the [render contract](#render-contract) and call `POST /render`.

For now this station only provides the renderer; subtitle + ffmpeg
composition lives in `libs/video-ops` / `libs/audio-ops` (Phase 7 Agent B).

---

## HTTP API

### `GET /healthz`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "chromium_path": "/Users/.../Google Chrome for Testing"
}
```

### `POST /render`

Request body:
```json
{
  "url": "http://localhost:5174",
  "durations": {
    "00_intro": [1200, 800],
    "01_body":  [2000, 500, 1500]
  },
  "out_dir": "/tmp/wvt-frames",
  "fps": 30,
  "viewport": [1920, 1080],
  "format": "png",
  "quality": 90,
  "chapter": null
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `url` | string | — | Web app URL (no query). `?render=1&chapter=N&start=K&fps=F` is appended automatically. |
| `durations` | `{chapterId: [stepDurMs, ...]}` | — | BTreeMap iterates keys in alphabetical order. Prefix IDs (`00_*`, `01_*`) to control chapter order. |
| `out_dir` | string | — | Frames + `manifest.json` written here. Created if absent. |
| `fps` | int | `30` | |
| `viewport` | `[w, h]` | `[1920, 1080]` | |
| `format` | `"png" \| "jpeg"` | `"png"` | |
| `quality` | int 1-100 | `90` | JPEG only. |
| `chapter` | int | `null` | If set, render only that chapter. Frame indices remain GLOBAL. |

Response:
```json
{
  "frames_dir": "/tmp/wvt-frames",
  "manifest_path": "/tmp/wvt-frames/manifest.json",
  "total_frames": 156,
  "captured_segments": 5,
  "wall_clock_seconds": 12.43
}
```

`manifest.json` (always describes the FULL plan, even with `chapter` set):
```json
{
  "fps": 30,
  "format": "png",
  "totalFrames": 156,
  "viewport": { "width": 1920, "height": 1080 },
  "segments": [
    {
      "chapterIdx": 0, "chapterId": "00_intro", "step": 0,
      "durMs": 1200, "startFrame": 0, "endFrame": 35, "frameCount": 36
    },
    ...
  ]
}
```

### `POST /shutdown` (dev only, `--dev` flag required)

Schedules `std::process::exit(0)` after the response flushes.

---

## Render contract

A web app is renderable iff it satisfies:

1. URL accepts query params `?render=1&chapter=N&start=K&fps=F` and starts
   at the requested step.
2. Exposes `window.__renderState = { chapter, step, chapterId, globalIndex,
   totalGlobal, stepDurationMs, done }` and updates it as the show
   progresses.
3. UI chrome (progress bars, controls, overlays) is hidden in render mode.
4. Step advancement is timer-driven (`setTimeout`) — virtual time will
   drive it. **Do not** depend on wall-clock audio events.
5. Animations use `@keyframes`, not `transition`. (CSS transitions don't
   advance under CDP virtual time even with all flags set.)
6. (Recommended) Skip `React.StrictMode` in render mode to avoid double-
   mount timer duplication.

Validated by Phase 0 spike (`src/bin/spike.rs`) — final translateX hits
500 across 5 × 200ms advance budgets, confirming compositor animations
DO progress under `Emulation.setVirtualTimePolicy { policy: "advance" }`
when the deterministic flag set in `src/flags.rs` is applied.

---

## Build & run

```bash
cd ~/workshop/stations/browser-render
cargo build --release          # writes to ~/.cargo/shared-target/release/
./target/release/browser-render --config config.yaml
# or via shared target:
~/.cargo/shared-target/release/browser-render --config config.yaml
```

Once registered (Phase 3 already done), `scripts/workshop_services.py` can
start / stop it like any other workshop station. The entry is marked
`optional: True` — heavy resource consumer, only run when needed.

```bash
# Manual probe
curl http://127.0.0.1:10221/healthz
```

### Chromium

The renderer needs a Chromium binary. Resolution order (see
`src/flags.rs::find_chrome`):

1. `$CHROME` env var.
2. Playwright cache (`~/Library/Caches/ms-playwright/chromium-*/...`).
3. macOS system Google Chrome (`/Applications/...`).
4. Linux `/usr/bin/{google-chrome,chromium-browser,chromium}`.

If you don't have Playwright installed, run once: `npx playwright install
chromium`.

---

## Tests

```bash
cargo test --release            # unit + smoke
cargo run --bin spike --release # Phase 0 sanity check
```

The smoke test spins up a minimal axum server serving a 2-step page, runs
the full render pipeline against it, and asserts:
- `total_frames == sum(durations × fps / 1000)`
- `manifest.json` shape matches the schema
- Pixel diff between first and last frame (animation moved)

---

## Implementation notes

- **Virtual time policy**: Always `advance` policy, never `pauseIfNetworkFetchesPending`.
  Vite dev server holds a persistent HMR WebSocket; the "pending fetches"
  variant waits on it forever. `advance` ignores network state.
- **Per-request user-data-dir**: Each render gets a unique
  `$TMPDIR/browser-render-<pid>-<nanos>-<counter>` and cleans up after.
  Prevents Chromium's singleton lock from blocking parallel renders.
- **About:blank bootstrap**: chromiumoxide's `new_page(url)` sometimes
  leaves the page on `about:blank` if `url` is `data:`. We open
  `about:blank` first then `goto()` the real target.
- **Global frame indices**: Even when `chapter=N` is set, frames are named
  by their position in the FULL plan. Workers can write to the same
  `out_dir` without collisions.

---

## Files

| Path | Purpose |
|---|---|
| `src/main.rs` | Binary entry: axum server + CLI |
| `src/lib.rs` | Library surface for tests + downstream Rust |
| `src/render.rs` | Core renderer (CDP virtual-time loop) |
| `src/flags.rs` | Chromium launch flags + binary discovery |
| `src/manifest.rs` | `manifest.json` schema + `build_plan()` |
| `src/api.rs` | HTTP route handlers |
| `src/config.rs` | YAML config loader (figment) |
| `src/bin/spike.rs` | Phase 0 sanity check |
| `tests/smoke.rs` | End-to-end render against self-hosted axum page |
| `config.yaml` | Service config (host, port, defaults) |
