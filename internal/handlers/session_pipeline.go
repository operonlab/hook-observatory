// Package handlers — session_pipeline.go
// SessionEnd handler — unified session pipeline (non-blocking background process).
// Replaces individual redact/extract/archive/reflect/log steps.
// Spawns a background process running the Python SDK pipeline.
package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("SessionEnd", core.Entry{
		Matcher:    "",
		Handler:    sessionPipelineHandle,
		Critical:   false,
		ModuleName: "session_pipeline",
	})
}

func sessionPipelineHandle(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	var data map[string]any
	if strings.TrimSpace(rawInput) != "" {
		_ = json.Unmarshal([]byte(rawInput), &data)
	}
	if data == nil {
		data = map[string]any{}
	}

	sessionID, _ := data["session_id"].(string)
	if sessionID == "" {
		return core.Allow()
	}

	transcriptPath, _ := data["transcript_path"].(string)

	home, err := os.UserHomeDir()
	if err != nil {
		return core.Allow()
	}

	// Python path
	python := filepath.Join(home, ".local", "bin", "python3")

	// Log directory
	logDir := filepath.Join(home, ".claude", "data", "session-pipeline")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return core.Allow()
	}

	// Build the inline Python code (mirrors Python impl)
	code := "import sys, os; " +
		"sys.path.insert(0, os.path.expanduser('~/workshop/libs/sdk-client')); " +
		"from sdk_client.session_pipeline import SessionPipelineClient; " +
		"SessionPipelineClient().run_pipeline(" + quoteStr(sessionID) + ", " + quoteStr(transcriptPath) + ")"

	_ = core.RunBackground([]string{python, "-c", code}, "")
	return core.Allow()
}

// quoteStr produces a Python repr-style string literal for simple strings.
func quoteStr(s string) string {
	// Use Go's JSON marshaling to get a safe quoted string, then convert to Python single-quotes
	b, _ := json.Marshal(s)
	// b is a JSON double-quoted string; Python can use it directly
	return string(b)
}
