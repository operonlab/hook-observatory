# hook-dispatcher — Go-native hook executor for Claude Code

Single statically-linked binary that handles all 10 [Claude Code hook
events](https://docs.claude.com/en/docs/claude-code/hooks) — PreToolUse,
PostToolUse, Stop, SessionStart, SessionEnd, UserPromptSubmit,
Notification, PreCompact, SubagentStop, and the OnError fallback — in-process.

Designed to drop into `~/.claude/hooks/hook-dispatcher` and replace
per-event Python / shell scripts with one cold-start-free executable.

## Migration note (2026-05-13)

This repository was historically `operonlab/hook-observatory` (Python +
FastAPI dashboard). As of v0.2.0 it is replaced by a Go binary. The old
Python source is preserved in the upstream Workshop monorepo at
`stations/_archive/hook-observatory-py/` and is no longer maintained
here.

If you previously installed the Python version:

1. Upgrade via Homebrew or the install script below.
2. Run `hook-dispatcher --install` (or `./install.sh`) to rewrite the 10
   hook entries in `~/.claude/settings.json` to point at the binary.
3. Remove the old `~/.claude/hooks/dispatcher.py` if it still exists.

## Install

### Homebrew (recommended)

```bash
brew tap operonlab/tap
brew install hook-observatory
hook-dispatcher --install   # registers hooks in ~/.claude/settings.json
```

### One-liner installer

```bash
curl -fsSL https://raw.githubusercontent.com/operonlab/hook-observatory/main/install.sh | bash
```

The installer detects your platform, downloads the matching binary from
the latest GitHub release, places it at `~/.claude/hooks/hook-dispatcher`,
and writes 10 hook entries into `~/.claude/settings.json`.

### From source

```bash
git clone https://github.com/operonlab/hook-observatory.git
cd hook-observatory
make install         # builds + deploys to ~/.claude/hooks/
```

Requires Go 1.25+, `jq`, and bash 4+.

### Uninstall

```bash
./install.sh --uninstall   # removes 10 hook entries (binary stays — rm it manually)
```

## Configuration

Copy `config.example.yaml` to `~/.hook-observatory/config.yaml` and toggle
handlers per your needs. Three handler tiers:

| Tier | Examples | Default |
|------|----------|---------|
| `core` | bash_safety, secret_scan, agent_naming, auto_format | All on |
| `workflow` | context_inject, utility_watchdog, claudemd_suggest | Most on |
| `integrations` | session_pipeline, voice_notify, memory_sync | Off — opt-in |

### Environment overrides

| Variable | Purpose |
|----------|---------|
| `HOOK_DISPATCHER_ROOT` | Override install dir (preferred) |
| `HOOK_OBSERVATORY_ROOT` | Backward-compat fallback (still honored) |

## Architecture

```
~/.claude/settings.json
   │  10 hook event entries point at →  ~/.claude/hooks/hook-dispatcher
   ▼
hook-dispatcher (Go binary)
   ├─ reads YAML config
   ├─ dispatches event JSON on stdin to matching handler
   ├─ in-process handlers (bash_safety, secret_scan, …)
   └─ external handlers shell out (e.g. sync-login.sh)
```

- Hook dispatch p50 ≈ 2 ms (22-13× faster than the Python interpreter
  cold-start path it replaced).
- No interpreter dependency — single 8-12 MB binary per platform.
- Spool writes to `~/.hook-observatory/spool/` for downstream consumers
  (session-channel, agent-metrics).

## Supported platforms

GitHub Actions builds these for every release:

- macOS arm64 (Apple Silicon)
- macOS amd64 (Intel)
- Linux amd64
- Linux arm64

Windows isn't shipped; WSL2 should work via the Linux amd64 binary but is
untested.

## Project layout

```
cmd/
  hook-dispatcher/      # main entry — reads stdin, dispatches event
  echo-guard-cli/       # standalone CLI: TTS spam guard
  pre-compact-cli/      # standalone CLI: pre-compact event helper
  shadow-compare/       # diff Go vs Python dispatcher output (dev tool)
internal/
  core/                 # config, event loop
  handlers/             # one file per handler
  clients/              # HTTP clients (memvault, litellm, …)
  portregistry/         # vendored Workshop port table
assets/
  tool_registry.json    # tool catalog metadata
config.example.yaml     # copy → ~/.hook-observatory/config.yaml
install.sh              # writes 10 hook entries into settings.json
Makefile                # build / install / test targets
```

## Development

```bash
go vet ./...
gofmt -d .
go test ./...
go build -o /tmp/hd ./cmd/hook-dispatcher
```

CI runs all of the above + cross-builds 4 platforms on every push.

## License

MIT — see `LICENSE` if present, otherwise inherited from upstream
`operonlab/hook-observatory`.

## Provenance

Maintained as a subtree mirror of `stations/hook-dispatcher/` in the
[Workshop](https://github.com/JonesHong/workshop) monorepo. Upstream
changes land here via `git subtree split + push --force`. Pull requests
filed against this repo are welcome but will be cherry-picked back to the
monorepo before merge.
