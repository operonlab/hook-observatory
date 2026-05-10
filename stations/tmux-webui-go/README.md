# tmux-webui

> Your tmux sessions, in any browser. Phone, tablet, laptop — same panes.

A web UI for tmux. Single static binary. Cross-device pane streaming with adaptive polling, virtual keys, ANSI rendering, autocomplete, file upload, and PWA install.

![demo placeholder](docs/demo.gif)

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/operonlab/tmux-webui/main/install.sh | sh
```

Then run:

```sh
tmux-webui
```

Open http://localhost:9527 in your browser.

## Use it from your phone

```sh
tmux-webui --lan
```

A QR code appears in the terminal. Scan it.

## Requires

- **tmux** — `brew install tmux` (macOS) / `sudo apt install tmux` (Debian/Ubuntu)
- macOS or Linux (arm64/amd64); Windows via WSL

## Run as a service

```sh
tmux-webui daemon install      # writes launchd plist (mac) or systemd user unit (linux)
tmux-webui daemon status
tmux-webui daemon logs
tmux-webui daemon uninstall
```

## Update

```sh
tmux-webui update --check
tmux-webui update
```

## Uninstall

```sh
tmux-webui uninstall -y
```

Removes binary, config, daemon, and uploads.

## More

- [Build from source](docs/from-source.md)
- [Remote access (LAN / Tailscale / Cloudflare / ngrok)](docs/remote-access.md)
- [Daemon setup](docs/daemon.md)
- [Homebrew install](docs/homebrew.md)
- [Workshop dogfood config](docs/dogfood-config.example.json)

## Status

| Phase | Status |
|-------|--------|
| 0 — Repo bootstrap | ✅ |
| 1 — Backend feature parity | ✅ |
| 2 — UX wrapping (`--lan` / QR / cobra / daemon / update / uninstall) | ✅ |
| 3 — Distribution (install.sh / goreleaser / Homebrew tap) | ✅ |
| 4 — Docs + first release | 🚧 first release pending |
| 5 — Workshop dogfood | ✅ smoke test passing |

## License

MIT — see [LICENSE](LICENSE)
