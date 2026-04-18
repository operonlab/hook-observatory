package handlers

// memory_sync.go — Go port of handlers/memory_sync.py
//
// PostToolUse+Edit/Write: detect memory file writes and trigger background
// sync to memvault via spawning the Python worker (memory_sync.py).

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Edit|Write",
		Handler:    memorySyncHandle,
		Critical:   false,
		ModuleName: "memory_sync",
	})
}

func memorySyncHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Edit" && toolName != "Write" {
		return core.Allow()
	}
	filePath, _ := toolInput["file_path"].(string)
	if filePath == "" {
		return core.Allow()
	}
	if !memorySyncIsMemoryFile(filePath) {
		return core.Allow()
	}

	home, _ := os.UserHomeDir()
	python := filepath.Join(home, ".local", "bin", "python3")
	script := filepath.Join(home, "workshop", "stations", "hook-observatory", "handlers", "memory_sync.py")

	realPath, err := filepath.EvalSymlinks(filePath)
	if err != nil {
		realPath = filePath
	}
	workshopCwd := filepath.Join(home, "workshop")
	_ = core.RunBackground([]string{python, script, realPath}, workshopCwd)
	fmt.Fprintf(os.Stderr, "[memory-sync] triggered sync: %s\n", filepath.Base(filePath))
	return core.Allow()
}

func memorySyncIsMemoryFile(path string) bool {
	home, _ := os.UserHomeDir()
	projectsDir := filepath.Join(home, ".claude", "projects")

	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		real = path
	}
	if !strings.HasPrefix(real, projectsDir) {
		return false
	}
	if !strings.Contains(real, "/memory/") {
		return false
	}
	base := filepath.Base(real)
	return strings.HasSuffix(base, ".md") && base != "MEMORY.md"
}

// memorySyncParseRawInput is a helper used by tests.
func memorySyncParseRawInput(raw string) map[string]any {
	var out map[string]any
	_ = json.Unmarshal([]byte(raw), &out)
	return out
}
