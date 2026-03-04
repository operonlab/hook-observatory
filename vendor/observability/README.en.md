---
source_hash: f67ef577
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Multi-Agent Observability (Community Project)

> Claude Code hooks real-time monitoring dashboard — tracks tool calls, task handoffs, and lifecycle events for multiple agents.

## Source

| Attribute | Value |
|------|------|
| **Author** | [@disler](https://github.com/disler) |
| **Repo** | [claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability) |
| **License** | Open Source (GitHub) |
| **Local Location** | `~/workshop/vendor/observability/` |

## Why is it in vendor/

This is a third-party community project that we use directly without refactoring it into the V2 architecture. The `vendor/` directory is specifically for storing this type of "ready-to-use" external tool.

## Architecture

```
Claude Agents → Hook Scripts → HTTP POST → Bun Server → SQLite → WebSocket → Vue Client
```

## Features

- Real-time tracking of hook events from multiple Claude Code agents
- Session tracking (identifies agents via source_app + session_id)
- Event filtering and search
- Real-time updates via WebSocket
- Vue.js dashboard UI

## Integration Method

Injects via Claude Code hooks (`~/.claude/settings.json`), with 9 event types:
- PreToolUse / PostToolUse
- PreBash / PostBash
- Notification
- SessionStart / SessionEnd
- etc.

The hook script (`observability-bridge.sh`) POSTs events to the Bun server.

## Local Operations

```bash
cd ~/workshop/vendor/observability
just server    # Start the Bun server
just client    # Start the Vue client
just dev       # Start both server + client simultaneously
```

## Technology Stack

- **Server**: Bun + SQLite
- **Client**: Vue.js
- **Communication**: WebSocket (real-time push)
- **Task Runner**: justfile

## Notes

- This project is not maintained by us; upstream updates require a manual `git pull`
- If custom features are needed, it is recommended to fork and then modify
- Belongs to step three of the SessionEnd pipeline, along with `stations/session-redactor`
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2674ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2805ms
