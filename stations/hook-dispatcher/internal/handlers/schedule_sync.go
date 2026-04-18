// Package handlers — schedule_sync.go
// PostToolUse handler for Edit/Write on schedules/manifest.json.
// Detects changes to schedules/manifest.json and triggers background sync.
package handlers

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Edit|Write",
		Handler:    scheduleSyncHandle,
		Critical:   false,
		ModuleName: "schedule_sync",
	})
}

func scheduleSyncHandle(_, _ string, toolInput map[string]any, _ string) core.HookResult {
	filePath, _ := toolInput["file_path"].(string)
	if !strings.Contains(filePath, "schedules/manifest.json") {
		return core.Allow()
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return core.Allow()
	}

	workshop := filepath.Join(home, "workshop")
	python := filepath.Join(home, ".local", "bin", "python3")
	syncScript := filepath.Join(workshop, "schedules", "sync.py")

	_ = core.RunBackground([]string{python, syncScript}, workshop)
	return core.Allow()
}
