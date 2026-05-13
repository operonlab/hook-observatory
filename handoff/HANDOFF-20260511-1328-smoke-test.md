# HANDOFF: smoke test the handoff protocol

**from**: pane %2  ·  **to**: anyone  ·  **created**: 2026-05-11

## Goal
Verify /handoff protocol publishes correctly and inbox shows path.

## Key Decisions
1. Use `handoffs` topic — separate from `broadcasts` so workers can filter
2. `handoff_path` lives in `_meta`, not message text — keeps text short

## Files Modified
- `~/.claude/commands/handoff.md` : new slash command
- `stations/session-channel/cli/channel.py` : added --meta param
- `stations/hook-dispatcher/.../session_channel.go` : inbox shows path

## Next Steps
1. Wait for human to test in a real session
2. If approved, write session-channel SKILL note for接手 behavior

## Risks / Pitfalls
- target_pane=null means broadcasts to everyone — may noise other panes
