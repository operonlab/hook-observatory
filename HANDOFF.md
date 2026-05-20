# hook-observatory — Stage 1/2/3 Handoff

> **Historical document — Stage 3 cutover completed 2026-04-17, full
> hook-observatory Python source archived 2026-05-13** (see
> `stations/_archive/hook-observatory-py/_DEPRECATED.md`). Kept for
> reference; the migration tables / Stage 2 split / dependency lists
> below describe the work as it stood during the cutover, not current
> state. `context_supervisor` was explicitly **not** ported to Go — the
> feature was abandoned 2026-05-13 (concept good, scoring inaccurate).

> Status: **Stage 3 ✅ PRODUCTION** — `~/.claude/settings.json` now calls Go binary for all 10 hook events
> Plan: `~/.claude/plans/p1-agent-majestic-hickey.md`
> Branch: main (uncommitted)
> Date: 2026-04-17
>
> **Live status:**
> - Settings.json backup: `~/.claude/settings.json.bak-20260417-154105`
> - Python fallback: active on panic (kill switch `HOOK_DISPATCHER_NO_FALLBACK=1`)
> - Shadow-compare: 100% match on 50 synthetic events, Go 2.19× faster
> - Dispatch latency: Go ~2 ms p50 vs Python ~46 ms p50 (22–13× faster depending on handler load)
> - Rollback: `cp ~/.claude/settings.json.bak-20260417-154105 ~/.claude/settings.json`

## Stage 1 Results

| Metric | Target | Actual |
|--------|--------|--------|
| Unit + integration tests | green | **55 pass, 0 fail** |
| Go vet / gofmt | clean | **clean** |
| Binary size | ~5 MB | **2.5 MB** |
| Dispatch latency p50 | ≤ 5 ms | **2.0 ms** (22.86× faster than Python 45.4 ms) |
| Dispatch latency p99 | ≤ 20 ms | **~6 ms** |

## What's Shipped

### Core (`internal/core/`)
- `result.go` — `HookResult` + merge accumulator (block > approve > passthrough)
- `config.go` — YAML loader, deep merge, `~` expansion, singleton `Cfg()`
- `runcmd.go` + `buffer.go` — subprocess helper with timeout, bounded output capture
- `dispatcher.go` — registry + phase-split routing (critical no-budget, deferrable 5 s budget) + panic recovery + output assembly

### Entry (`cmd/hook-observatory/main.go`)
- argv[1] = event_type, stdin = JSON, stdout = JSON/passthrough, always exit 0
- Outermost panic recovery guarantees fail-open

### Golden sample handlers (`internal/handlers/`)
- `observability.go` — all 10 event types, JSONL spool append
- `session_cost.go` — Stop event, writes `~/.claude/data/session-cost/sessions.jsonl`
- `bash_safety.go` — PreToolUse+Bash, regex critical handler (rm/sudo/force push/pnpm/…)

### Build (`Makefile`)
- `make build` → `bin/hook-observatory` with `-s -w` ldflags
- `make test` / `make vet` / `make bench`
- `make install` → copies binary to `~/.claude/hooks/hook-observatory`

## Public API Frozen for Stage 2

Stage 2 agents **must not touch** `internal/core/*`. Interact only through:

```go
import "github.com/joneshong/hook-observatory/internal/core"

func init() {
    core.Register("PreToolUse", core.Entry{
        Matcher:    "Bash",          // "" = match all; "A|B" = match A or B
        Handler:    myHandler,        // func(eventType, toolName, toolInput, rawInput) HookResult
        Critical:   false,            // true = no 5s budget
        ModuleName: "my_handler",     // matches config.yaml handlers.*.my_handler key
    })
}

func myHandler(eventType, toolName string, toolInput map[string]any, rawInput string) core.HookResult {
    // return core.Allow() | core.Block("...") | core.Approve() | core.Message("...") | core.TextResult("...")
    return core.Allow()
}
```

Available helpers:
- `core.Cfg()` — singleton config accessor (`GetPath`, `GetService`, `GetTool`, `GetSpoolDir`, …)
- `core.RunCmd(args, stdin, timeout, cwd)` — subprocess with timeout + fail-safe
- `core.RunBackground(args, cwd)` — detached fire-and-forget

## Stage 2 Dispatch Plan (3 parallel agents)

| Agent | Scope | Handlers | Est. hours |
|-------|-------|----------|-----------:|
| **A — high-freq / regex** | Critical hot path, pure logic | `secret_scan`, `skill_security`, `rtk_rewrite`, `verify_commit`, `agent_naming`, `plan_impl_gate` | 12–18 |
| **B — IO / subprocess** | File state + external CLI | `auto_format`, `context_inject`, `cleanup_versions`, `claudemd_suggest`, `review_gate`, `schedule_sync`, `session_channel`, `session_pipeline`, `session_namer`, `utility_watchdog`, `instinct_distiller`, `attitude_signal` | 18–26 |
| **C — HTTP / integrations** | LLM + HTTP clients + Redis | `anvil_telemetry`, `annotate_insight_hook`, `context_relay`, `memory_sync`, `pm_autopilot`, `read_edit_ratio`, `relay_signal`, `sentinel_notify`, `verify_completion`, `external`, `issue_sync` | 20–30 |
| **D (after C)** | Boss fight | `context_supervisor` (1002 LOC, LLM + embedding + 3-layer heuristic) | 25–40 |

### Rules for Stage 2 agents

1. **One handler per file**, package `handlers`, filename mirrors Python (`auto_format.go`, not `autoformat.go`).
2. **Self-register in `init()`** — do not touch any registry central file.
3. **Write `<name>_test.go`** with ≥3 cases (normal / edge / error).
4. **Must pass** `go test ./...`, `go vet ./...`, `gofmt -d .`.
5. **Do not modify `internal/core/*`** — open an issue in `~/workshop/stations/hook-observatory/issues/` if you need a new shared util.
6. **Match Python fail-open semantics** — every handler returns `core.Allow()` on error, never panics past the recover boundary.
7. **Parity over cleverness** — if Python has a quirky regex, mirror it; consistency with the shadow-compare is the goal.

## Not Yet Built (Stage 2 dependencies)

These shared `internal/clients/` packages don't exist yet — whoever needs them first builds them:

| Client | First needed by | Shape |
|--------|-----------------|-------|
| `clients/litellm.go` | `annotate_insight_hook`, `context_supervisor` | POST to `http://127.0.0.1:4000`, streaming off |
| `clients/embedding.go` | `context_supervisor` | subprocess pipe to `~/.venvs/omlx/embed_worker.py` |
| `clients/memvault.go` | `annotate_insight_hook`, `memory_sync` | HTTP wrapper around `libs/sdk-client/memvault` |
| `clients/redis.go` | `relay_signal` | `github.com/redis/go-redis/v9` thin wrapper |
| `clients/github.go` | `pm_autopilot`, `issue_sync` | `gh` CLI subprocess, parse JSON output |

## Deployment (Stage 3 only — don't do this yet)

```json
// ~/.claude/settings.json — change after Stage 3 shadow validation passes
"PreToolUse": [{
  "type": "command",
  "command": "~/.claude/hooks/hook-observatory PreToolUse",
  "timeout": 20
}]
```

Python dispatcher stays in place as fallback during Stage 3 shadow (48 h) + monitored primary (14 d).
