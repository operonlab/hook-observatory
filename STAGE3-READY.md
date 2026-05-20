# Stage 3 — Ready for settings.json Switch

> **Historical document — Stage 3 went live 2026-04-17.** Python source
> was fully archived 2026-05-13 (see
> `stations/_archive/hook-observatory-py/_DEPRECATED.md`); `context_supervisor`
> stayed out of parity baseline (line 57) and was eventually abandoned
> rather than ported.

> Status: Binary installed, shadow 100% match, Python fallback armed
> Date: 2026-04-17

## What's Ready

| Artifact | Status |
|----------|--------|
| Go binary `~/.claude/hooks/hook-observatory` (7.3 MB) | ✅ installed |
| Shadow-compare tool `bin/shadow-compare` | ✅ built |
| 50-fixture shadow replay | ✅ **100% match**, Go 2.19× faster |
| Python fallback (panic → exec dispatcher.py) | ✅ in main.go |
| Kill switch `HOOK_DISPATCHER_NO_FALLBACK=1` | ✅ |
| All unit + integration tests | ✅ **133 pass / 0 fail** |

## Proposed `~/.claude/settings.json` Change

10 hook entries, all of the form:

```diff
-  "command": "/Users/joneshong/.local/bin/python3 ~/.claude/hooks/dispatcher.py <EVENT>"
+  "command": "/Users/joneshong/.claude/hooks/hook-observatory <EVENT>"
```

Affected event types: `Notification`, `PostToolUse`, `PreCompact`, `PreToolUse`, `SessionEnd`, `SessionStart`, `Stop`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit`.

## Switch Options

### Option A — Full swap (recommended after manual smoke in new session)
```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)
sed -i '' 's|/Users/joneshong/.local/bin/python3 ~/.claude/hooks/dispatcher.py |/Users/joneshong/.claude/hooks/hook-observatory |g' ~/.claude/settings.json
```

### Option B — Gradual (low-risk events first)
Swap only these 4 for 30-min observation:
- `Notification`, `PreCompact`, `SubagentStart`, `SessionEnd`

Then rest.

### Option C — Rollback
```bash
cp ~/.claude/settings.json.bak-<ts> ~/.claude/settings.json
```
Takes effect on next hook trigger.

## Safety Net

1. **Inside Go binary**: any panic → `exec python3 ~/.claude/hooks/dispatcher.py`, stdin/args passed through
2. **Environment kill switch**: `HOOK_DISPATCHER_NO_FALLBACK=1` disables the fallback (emergency Python forced via direct edit)
3. **File-level rollback**: copy back `.bak` file, next hook firing picks it up

## Known Shadow-Compare Caveats

- Shadow fixtures are synthetic (50 common payloads) — production may emit shapes we haven't seen
- `context_supervisor.py` is disabled in Python registry → not part of parity baseline
- Spool had only 14 real events available; synthetic coverage is the primary signal
