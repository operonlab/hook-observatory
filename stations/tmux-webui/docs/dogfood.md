# Dogfooding tmux-webui

> "Eat your own dog food" — run the thing you built as your daily driver before you ship it to anyone else.

Before a v0.1.0 release, the maintainer runs `tmux-webui` (Go) in place of the Python version that's been in production for months. The point is to surface bugs only a real user would notice — connection drops mid-`htop`, weird CJK wrapping on a 430px phone screen, a forgotten `Enter` after `Send`.

## Why dogfood matters here

`tmux-webui` is small but touches a lot of edges: a WebSocket FSM, tmux subprocess output parsing across versions, a service worker that iOS Safari is famously hostile to, file uploads, fit-mode layout save/restore. Unit tests catch the obvious; only continuous use catches the rest.

The CSS fixes, the missing `send-keys Enter`, the `switch_window` not refreshing the view — all surfaced during the first two hours of dogfooding. None of those would have shown up in CI.

## How to dogfood your own tmux-webui

Whether you're the original author or a contributor on a feature branch, the recipe is the same:

1. **Build with version stamps** so you can tell which build you're running:

   ```sh
   HASH=$(git rev-parse --short HEAD)
   DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   go build -trimpath -ldflags "-s -w \
     -X github.com/operonlab/tmux-webui/internal/buildinfo.Version=0.1.0-trial \
     -X github.com/operonlab/tmux-webui/internal/buildinfo.GitHash=$HASH \
     -X github.com/operonlab/tmux-webui/internal/buildinfo.BuildDate=$DATE" \
     -o ~/.local/bin/tmux-webui ./cmd/tmux-webui
   ```

2. **Write a config** that matches your real environment, not the OSS defaults. Example: [`dogfood-config.example.json`](dogfood-config.example.json) shows how to wire up a real metrics provider (sysmon HTTP), point autocomplete at `~/.claude/`, and enable an optional relay backend. Drop yours at `~/.config/tmux-webui/config.json`.

3. **Replace the production binary, keep the old one as fallback**. If you have a service supervisor:

   ```sh
   # Stop the previous binary (Python or older Go)
   <supervisor> stop tmux-webui
   # Point supervisor at ~/.local/bin/tmux-webui
   # Start it
   <supervisor> start tmux-webui
   ```

   Keep the old binary path commented in your supervisor config so a one-line revert is enough if something breaks.

4. **Use it for at least a week**, on every device you'll deploy to. Phone, tablet, laptop, ssh-only headless, PWA-installed, fresh-incognito, behind a Cloudflare tunnel. Each is a different bug surface.

5. **Log every surprise**, even cosmetic ones. The user who finds a 1px mis-alignment will not file an issue — they just stop using your tool.

## Workshop's specific dogfood setup

This OSS repo was extracted from a monorepo where it had been running as Python on port 10105 for months. The cutover:

- `scripts/workshop_services.py` rewires the supervisor `cmd` from `uv run server.py` to `~/.local/bin/tmux-webui serve --config ~/.config/tmux-webui/config.json`. A code comment marks the old line so revert is a one-line `sed`.
- nginx reverse proxy at `/apps/tmux/` keeps pointing at `127.0.0.1:10105`; only the process listening on that port changes.
- The Python source under `stations/tmux-webui/` stays on disk, untouched. If the Go version misbehaves on day three, switching back is two commands and zero rebuilds.

That fallback path is the whole point. Dogfood without an exit ramp is just a deployment.

## What "passes" the dogfood gate

Soft signals (cumulative over the week):

- All flows used in normal operation work without surprise: opening sessions, switching windows, sending input, file upload, ANSI rendering, virtual keyboard, gestures.
- No process restarts caused by `tmux-webui` itself. (Restarts caused by upstream tmux are tmux's problem.)
- Memory stays bounded — no slow leak from un-closed WS goroutines.
- iOS PWA stays installable and survives offline → online.

Hard signals (any one of these → revert):

- Service worker stuck on a stale build that won't update.
- `send-keys` corrupting input under heavy paste-buffer usage.
- WebSocket disconnects faster than the heartbeat can detect.
- Any data loss (pane content overwritten before being read).

## After the week

If everything's quiet → tag `v0.1.0`, [release](release.md) flows through goreleaser, OSS users can `curl | sh`.

If something blocked → revert in the supervisor, file the bug here, fix on a feature branch, dogfood again. There's no shame in a postponed release; there is shame in shipping a broken one.
