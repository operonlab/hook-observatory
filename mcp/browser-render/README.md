# Browser-Render MCP Server

MCP adapter for the `browser-render` station — headless browser frame capture + video composition for Remotion/web-based presentation projects.

## Architecture

```
Claude Code ──MCP──► browser-render/server.py ──SDK──► sdk_client.browser_render
                                                              │
                                                              ▼
                                               stations/browser-render (HTTP station)
                                               Playwright/Chromium (headless)
                                               FFmpeg (composition)
```

- **MCP layer** (`mcp/browser-render/server.py`): Tool registration, argument parsing, markdown formatting
- **SDK layer** (`libs/sdk-client/sdk_client/browser_render.py`): HTTP client to the station (Agent C deliverable)
- **Station layer** (`stations/browser-render/`): Actual headless browser + FFmpeg (Agent A deliverable)

## Tools

| Tool | Description | Required Args |
|------|-------------|---------------|
| `healthz` | Check station + browser liveness | — |
| `probe_durations` | Extract chapter/slide durations from Remotion project | `project_root` |
| `build_subtitles` | Generate SRT + VTT from project transcript data | `project_root`, `out_dir` |
| `render_url_to_frames` | Capture a URL as PNG frame sequence | `url`, `durations`, `out_dir` |
| `compose_final` | Merge frames + audio → final MP4 | `frames_dir`, `audio_dir`, `out_dir` |
| `render_pipeline` | Full end-to-end pipeline (probe→subtitle→render→compose) | `project_root`, `dev_url`, `out_dir` |

## Typical Claude Code Workflows

### 1. Check station is up before starting

```
User: Check if browser-render is ready.

Claude: [calls healthz()]
## Browser-Render Station Health: OK
| Component | Status |
| Station   | ok     |
| Headless Browser | alive |
| Station URL | http://127.0.0.1:10204 |
```

### 2. Discover project structure before rendering

```
User: What chapters are in ~/workshop/lab/slides-demo?

Claude: [calls probe_durations(project_root="/Users/joneshong/workshop/lab/slides-demo")]
## Project Duration Probe
| Slide Count | 5 |
| Total Duration | 42.5s (42500 ms) |

### Chapters
| # | Name      | Duration (ms) |
|---|-----------|--------------|
| 1 | intro     | 8000          |
| 2 | problem   | 10000         |
| 3 | solution  | 12000         |
| 4 | demo      | 8500          |
| 5 | outro     | 4000          |
```

### 3. Full pipeline (most common)

```
User: Render the slides-demo project to ~/workshop/outputs/video/slides-demo/.

Claude: [calls render_pipeline(
    project_root="/Users/joneshong/workshop/lab/slides-demo",
    dev_url="http://localhost:3000",
    out_dir="/Users/joneshong/workshop/outputs/video/slides-demo",
    fps=30
)]
## Browser-Render Pipeline Complete
| MP4    | `/Users/joneshong/workshop/outputs/video/slides-demo/final.mp4` |
| SRT    | `.../subtitles.srt` |
| VTT    | `.../subtitles.vtt` |
| Total Frames | 1275 |
| Wall Clock   | 94.3s |
```

### 4. Incremental: render one chapter, compose separately

```
User: Re-render just the "demo" chapter of slides-demo.

Claude:
1. [calls render_url_to_frames(
    url="http://localhost:3000/?chapter=demo",
    durations="8500",
    out_dir="/Users/joneshong/workshop/outputs/video/slides-demo/frames/demo",
    fps=30,
    chapter="demo"
)]

2. [calls compose_final(
    frames_dir="...frames/demo",
    audio_dir="...audio",
    out_dir="...final"
)]
```

## MCP Registration

Registered via `~/.mcpproxy/mcp_config.json` (lazy-wrapper with 30-min idle timeout):

```json
{
  "name": "browser-render",
  "protocol": "stdio",
  "command": "/Users/joneshong/.local/bin/mcp-lazy-wrapper",
  "args": [
    "--idle-timeout", "1800",
    "--name", "browser-render",
    "--tools-cache", "/Users/joneshong/workshop/mcp/browser-render/tools_cache.json",
    "--",
    "/Users/joneshong/.local/bin/python3",
    "/Users/joneshong/workshop/mcp/browser-render/server.py"
  ],
  "env": { "PYTHONIOENCODING": "utf-8" },
  "enabled": true
}
```

## Restarting mcpproxy (after config change)

```bash
launchctl kickstart -k gui/$(id -u)/com.user.mcpproxy
# or if not managed by launchd:
pkill -f mcpproxy && mcpproxy &
```

> Note: The `tools_cache.json` allows mcp-lazy-wrapper to serve tool metadata
> without starting the Python process — the server only starts when a tool is actually called.

## SDK Availability

The SDK (`sdk_client.browser_render`) is delivered by Agent C (parallel task).
Until it lands, all tools return a descriptive error:

```
## Error: SDK Not Available
Tool `render_pipeline` requires `sdk_client.browser_render` (Agent C deliverable).
ImportError: No module named 'sdk_client.browser_render'
```

No action needed — once Agent C commits `sdk_client/browser_render.py`, the tools work automatically.

## Expected SDK Contract

```python
class BrowserRenderClient:
    def pipeline(project_root, dev_url, out_dir, fps=30)
        -> PipelineResult(mp4_path, srt_path, vtt_path, total_frames, wall_clock_seconds)

    def render(url, durations: list[int], out_dir, fps=30, chapter=None)
        -> RenderResult(mp4_path, frames_dir, manifest_path, frame_count)

    def probe(project_root)
        -> dict(chapters: [{name, duration_ms}], total_ms, slide_count)

    def build_subtitles(project_root, out_dir)
        -> dict(srt_path, vtt_path, cue_count)

    def compose(frames_dir, audio_dir, out_dir)
        -> dict(mp4_path, duration_seconds, frame_count)

    def healthz()
        -> dict(status: "ok"|"error", browser_alive: bool, station_url: str)
```
