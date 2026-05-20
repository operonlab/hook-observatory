package handlers

// pre_compact.go — PreCompact hook handler
//
// Triggered when Claude Code is about to compact the conversation context.
// This handler:
//   1. Parses the PreCompact payload (session_id, trigger, cwd).
//   2. Writes a checkpoint JSON to ~/.claude/data/pre-compact/<session_id>.json
//      so a future session can resume from a known state.
//   3. Returns a hint message via core.Message() reminding Claude to
//      externalize state following the Write→Select→Compress→Isolate strategy.
//
// First version intentionally omits live context-pressure detection (the OMC
// preemptive-compaction approach). Pressure signals are already handled by
// context_relay.go. This handler focuses on durable state persistence.
//
// NOT registered in this file — call RegisterPreCompact() from doc.go or
// init() once the hook is confirmed stable. See doc.go for wiring guidance.

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

// PreCompactPayload is the JSON shape sent by Claude Code for the PreCompact event.
type PreCompactPayload struct {
	SessionID      string `json:"session_id"`
	Trigger        string `json:"trigger"` // "manual" | "auto"
	Cwd            string `json:"cwd"`
	TranscriptPath string `json:"transcript_path"`
}

// PreCompactCheckpoint is written to disk for session-resume purposes.
type PreCompactCheckpoint struct {
	CreatedAt string `json:"created_at"`
	SessionID string `json:"session_id"`
	Trigger   string `json:"trigger"`
	Cwd       string `json:"cwd"`
}

// preCompactHint is the markdown hint injected into Claude's context via message.
// Mirrors the Write→Select→Compress→Isolate strategy from context-optimization.md.
const preCompactHint = `## PreCompact — State Externalize Checklist

Context is about to be compacted. Before proceeding, consider externalising:

1. **Write** — If there is in-progress implementation, save a HANDOFF.md with:
   - Goal (one line)
   - Key Decisions (numbered, with WHY)
   - Files Modified (path : what changed)
   - Next Steps (concrete, with file paths)

2. **Select** — Keep only what is load-bearing after compaction. Drop raw
   transcripts and large file dumps from active context.

3. **Compress** — Summarise completed sub-tasks rather than retaining details.

4. **Isolate** — Offload any remaining independent sub-problems to sub-agents
   so the main context stays lean.

> Checkpoint saved to ~/.claude/data/pre-compact/ for session resume.`

// preCompactHandle is the handler for the PreCompact event.
func preCompactHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	if eventType != "PreCompact" {
		return core.Allow()
	}

	var payload PreCompactPayload
	if rawInput != "" {
		// Tolerate parse errors — fail open.
		_ = json.Unmarshal([]byte(rawInput), &payload)
	}

	// Write checkpoint; errors are non-fatal.
	if err := pcWriteCheckpoint(payload); err != nil {
		// Log to stderr for observability, but do not block compaction.
		fmt.Fprintf(os.Stderr, "[pre_compact] checkpoint write error: %v\n", err)
	}

	return core.Message(preCompactHint)
}

// pcWriteCheckpoint persists a compact checkpoint JSON to:
//
//	~/.claude/data/pre-compact/<session_id>.json
//
// If session_id is empty, uses "unknown" to still produce a file.
func pcWriteCheckpoint(payload PreCompactPayload) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("userHomeDir: %w", err)
	}

	dir := filepath.Join(home, ".claude", "data", "pre-compact")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("mkdirAll %s: %w", dir, err)
	}

	sessionID := payload.SessionID
	if sessionID == "" {
		sessionID = "unknown"
	}
	trigger := payload.Trigger
	if trigger == "" {
		trigger = "auto"
	}

	checkpoint := PreCompactCheckpoint{
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
		SessionID: sessionID,
		Trigger:   trigger,
		Cwd:       payload.Cwd,
	}

	data, err := json.MarshalIndent(checkpoint, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	outPath := filepath.Join(dir, sessionID+".json")
	if err := os.WriteFile(outPath, data, 0o644); err != nil {
		return fmt.Errorf("writeFile %s: %w", outPath, err)
	}

	return nil
}

// RegisterPreCompact wires the handler into the dispatcher registry.
// Kept as a named function so tests can call it after core.Reset() without
// triggering a double-register from init().
func RegisterPreCompact() {
	core.Register("PreCompact", core.Entry{
		Handler:    preCompactHandle,
		Critical:   false,
		ModuleName: "pre_compact",
	})
}

// init wires the handler at binary startup. Tests Reset() the registry and
// re-register via RegisterPreCompact() as needed.
func init() {
	RegisterPreCompact()
}
