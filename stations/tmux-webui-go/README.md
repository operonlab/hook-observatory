# tmux-webui

> Your tmux sessions, in any browser. Phone, tablet, laptop — same panes.

Web UI for tmux. Single static binary. Cross-device pane streaming with adaptive polling, virtual keys, ANSI rendering, autocomplete, file upload, and PWA install.

> Currently a Go rewrite of the original Python (FastAPI) `tmux-webui`.
> Under active development — not yet released.

## Status

| Phase | Status |
|-------|--------|
| 0 — Repo bootstrap | in progress |
| 1 — Backend feature parity | pending |
| 2 — UX wrapping (`--lan` / QR / tmux check / `--open`) | pending |
| 3 — Distribution (install.sh / goreleaser / Homebrew tap / selfupdate) | pending |
| 4 — Docs + first release `v0.1.0` | pending |

## Build from source

```sh
git clone https://github.com/operonlab/tmux-webui
cd tmux-webui
go build ./cmd/tmux-webui
./tmux-webui --version
```

## License

MIT — see [LICENSE](LICENSE)
