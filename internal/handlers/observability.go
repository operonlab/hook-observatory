package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	entry := core.Entry{
		Handler:    observabilityHandle,
		ModuleName: "observability",
	}
	for _, ev := range []string{
		"PreToolUse", "PostToolUse", "Stop", "Notification",
		"SessionEnd", "UserPromptSubmit", "SessionStart",
		"SubagentStart", "SubagentStop", "PreCompact",
	} {
		core.Register(ev, entry)
	}
}

// observabilityHandle is the Go port of handlers/observability.py.
//
// Appends every hook event as a single JSONL line to the spool file.
// Format matches Python byte-for-byte:
//
//	{"event_type":"...","ts":"YYYY-MM-DDTHH:MM:SS.000Z","data":{...}}
func observabilityHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	if strings.TrimSpace(rawInput) == "" {
		return core.Allow()
	}

	spoolDir := core.Cfg().GetSpoolDir()
	if err := os.MkdirAll(spoolDir, 0o755); err != nil {
		return core.Allow()
	}
	spoolFile := filepath.Join(spoolDir, "events.jsonl")

	var data any
	if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
		return core.Allow()
	}

	// Python uses datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z").
	// Note the hardcoded ".000Z" — milliseconds are always zero in Python impl.
	ts := time.Now().UTC().Format("2006-01-02T15:04:05") + ".000Z"

	entry := map[string]any{
		"event_type": eventType,
		"ts":         ts,
		"data":       data,
	}
	line, err := json.Marshal(entry)
	if err != nil {
		return core.Allow()
	}

	f, err := os.OpenFile(spoolFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return core.Allow()
	}
	defer f.Close()
	f.Write(line)
	f.Write([]byte("\n"))

	return core.Allow()
}
