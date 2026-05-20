# hook-observatory — Go-native hook executor for Claude Code

Single statically-linked binary that handles all 10 [Claude Code hook
events](https://docs.claude.com/en/docs/claude-code/hooks) — PreToolUse,
PostToolUse, Stop, SessionStart, SessionEnd, UserPromptSubmit,
Notification, PreCompact, SubagentStop, and the OnError fallback — in-process.

Designed to drop into `~/.claude/hooks/hook-observatory` and replace
per-event Python / shell scripts with one cold-start-free executable.

## Migration notes

### 2026-05-21 — binary renamed back to `hook-observatory`

During the 2026-05-13 Python → Go rewrite the binary and install path
were briefly renamed to `hook-dispatcher`. As of v0.2.2 the binary is
renamed back to `hook-observatory` so the install path, GitHub repo,
Homebrew formula, and blog narrative all line up.

If you installed v0.2.0 or v0.2.1:

```bash
brew uninstall hook-observatory
rm -f ~/.claude/hooks/hook-dispatcher
brew update
brew install operonlab/tap/hook-observatory
~/.claude/hooks/hook-observatory --install   # or ./install.sh
```

### 2026-05-13 — Python → Go rewrite

This repository was historically a Python + FastAPI dashboard. As of
v0.2.0 the hook execution path is a single Go binary. The old Python
source is preserved in the upstream Workshop monorepo at
`stations/_archive/hook-observatory-py/` and is no longer maintained
here.

## Install

### Homebrew (recommended)

```bash
brew tap operonlab/tap
brew install hook-observatory
hook-observatory --install   # registers hooks in ~/.claude/settings.json
```

### One-liner installer

```bash
curl -fsSL https://raw.githubusercontent.com/operonlab/hook-observatory/main/install.sh | bash
```

The installer detects your platform, downloads the matching binary from
the latest GitHub release, places it at `~/.claude/hooks/hook-observatory`,
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
| `HOOK_OBSERVATORY_ROOT` | Override install dir (preferred) |
| `HOOK_DISPATCHER_ROOT` | Backward-compat fallback (honored for 2026-05-13 → 2026-05-21 installs) |

## Architecture

```
~/.claude/settings.json
   │  10 hook event entries point at →  ~/.claude/hooks/hook-observatory
   ▼
hook-observatory (Go binary)
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
  hook-observatory/      # main entry — reads stdin, dispatches event
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
go build -o /tmp/hd ./cmd/hook-observatory
```

CI runs all of the above + cross-builds 4 platforms on every push.

## License

MIT — see `LICENSE` if present, otherwise inherited from upstream
`operonlab/hook-observatory`.

## Provenance

Maintained as a subtree mirror of `stations/hook-observatory/` in the
[Workshop](https://github.com/JonesHong/workshop) monorepo. Upstream
changes land here via `git subtree split + push --force`. Pull requests
filed against this repo are welcome but will be cherry-picked back to the
monorepo before merge.
