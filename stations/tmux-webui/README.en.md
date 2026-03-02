---
source_hash: ce2ae91d
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# tmux Web UI Workstation

> Control tmux from your browser — real-time multi-pane control, system metrics display, and LLM usage at a glance.

## Positioning

An independent workstation under Workshop `stations/`. Provides a web interface to manage tmux sessions/windows/panes, while also displaying system metrics (CPU, RAM, Disk, Network) and LLM usage.

## V1 Assets

| Component | Location | Description |
|------|------|------|
| `server.py` | `~/Claude/projects/tmux-webui/` | Single-file Python, aiohttp, 75KB |
| tmux status scripts | `~/.tmux/scripts/` | net-speed, cpu-status, mem-status, disk-status |
| sysmon data | `/tmp/workshop-sysmon-latest.json` | LLM usage fallback |

## Features

| Feature | Description |
|------|------|
| **Session Browsing** | List all tmux sessions + windows + panes |
| **Pane Control** | Send commands to a tmux pane from the browser |
| **Multi-pane View** | Monitor the output of multiple panes simultaneously |
| **System Metrics** | Real-time status for CPU / RAM / Disk / Network |
| **LLM Usage** | Claude 5h/7d, Codex 5h/7d, Gemini Pro usage |

## Launch

```bash
uv run ~/Claude/projects/tmux-webui/server.py              # port 8765
uv run ~/Claude/projects/tmux-webui/server.py --port 3000   # custom port
```

## Technology

- **Language**: Python 3.12
- **Framework**: aiohttp (Single file, inline script dependencies)
- **Dependencies**: `aiohttp` (The only external dependency)
- **Frontend**: Embedded HTML/CSS/JS (inside server.py)
- **Default Port**: 8765

## Directory Structure (Planned)

```
stations/tmux-webui/
├── README.md          ← This document
└── server.py          ← Main program (migrated from V1)
```

## Migration Plan

1. Copy `server.py` to `stations/tmux-webui/`
2. Update the launch command path
3. (Optional) Integrate LLM usage data source with the llm-usage station

## Dependencies

- **tmux** — Must be installed locally
- **tmux status scripts** (`~/.tmux/scripts/`) — For system metrics display
- **sysmon** (Optional) — LLM usage fallback

## References

- V1 Location: `~/Claude/projects/tmux-webui/`
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3618ms
