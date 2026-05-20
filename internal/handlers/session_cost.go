package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("Stop", core.Entry{
		Handler:    sessionCostHandle,
		ModuleName: "session_cost",
	})
}

// sessionCostHandle is the Go port of handlers/session_cost.py.
//
// The Python version uses a process-scoped counter dict that starts empty on
// each dispatcher invocation, so response_index is effectively always 1 in
// practice (one dispatch per process). We replicate that behavior exactly.
func sessionCostHandle(_, toolName string, _ map[string]any, rawInput string) core.HookResult {
	if strings.TrimSpace(rawInput) == "" {
		return core.Allow()
	}

	sessionID := parseSessionID(rawInput)
	if sessionID == "" {
		sessionID = "unknown"
	}

	dataDir := core.Cfg().GetPath("data_dir")
	if dataDir == "" {
		home, _ := os.UserHomeDir()
		dataDir = filepath.Join(home, ".claude", "data")
	}
	costDir := filepath.Join(dataDir, "session-cost")
	if err := os.MkdirAll(costDir, 0o755); err != nil {
		return core.Allow()
	}
	sessionsFile := filepath.Join(costDir, "sessions.jsonl")

	ts := time.Now().UTC().Format("2006-01-02T15:04:05Z")
	entry := map[string]any{
		"session_id":     sessionID,
		"ts":             ts,
		"tool_name":      toolName,
		"response_index": 1, // matches Python per-process counter reset
	}
	line, err := json.Marshal(entry)
	if err != nil {
		return core.Allow()
	}

	f, err := os.OpenFile(sessionsFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return core.Allow()
	}
	defer f.Close()
	f.Write(line)
	f.Write([]byte("\n"))

	return core.Allow()
}

func parseSessionID(raw string) string {
	var parsed map[string]any
	if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
		return ""
	}
	if v, ok := parsed["session_id"].(string); ok && v != "" {
		return v
	}
	if ti, ok := parsed["tool_input"].(map[string]any); ok {
		if v, ok := ti["session_id"].(string); ok && v != "" {
			return v
		}
	}
	return ""
}
