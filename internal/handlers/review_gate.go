// Package handlers — review_gate.go
// Stop hook handler — git-based review checklist.
// Checks for uncommitted code changes.
// Config: ~/.claude/data/review-gate.json {"enabled": false}
// Default: message-only; {"enabled": true}: block mode.
package handlers

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

var reviewGateCodeExts = map[string]struct{}{
	".py": {}, ".ts": {}, ".tsx": {}, ".js": {}, ".jsx": {},
	".mjs": {}, ".cjs": {}, ".rs": {}, ".go": {}, ".java": {},
	".c": {}, ".cpp": {}, ".h": {}, ".hpp": {}, ".sql": {},
	".sh": {}, ".bash": {}, ".zsh": {},
}

var reviewGateIgnorePatterns = map[string]struct{}{
	"test":         {},
	"tests":        {},
	"__pycache__":  {},
	"node_modules": {},
	".worktrees":   {},
	"dist":         {},
	"build":        {},
	".git":         {},
}

func init() {
	core.Register("Stop", core.Entry{
		Matcher:    "",
		Handler:    reviewGateHandle,
		Critical:   true,
		ModuleName: "review_gate",
	})
}

func reviewGateHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	if eventType != "Stop" {
		return core.Allow()
	}

	var cwd string
	if strings.TrimSpace(rawInput) != "" {
		var parsed map[string]any
		if err := json.Unmarshal([]byte(rawInput), &parsed); err == nil {
			cwd, _ = parsed["cwd"].(string)
		}
	}

	hasChanges, changedFiles := reviewGateHasCodeChanges(cwd)
	if !hasChanges {
		return core.Allow()
	}

	cfg := reviewGateLoadConfig()
	fileSummary := reviewGateFileSummary(changedFiles)

	if enabled, _ := cfg["enabled"].(bool); enabled {
		return core.Block(fmt.Sprintf(
			"Review gate: %d uncommitted code change(s) detected (%s). "+
				"Review or commit before ending session.",
			len(changedFiles), fileSummary,
		))
	}

	return core.Message(fmt.Sprintf("⚠ %d uncommitted code change(s): %s", len(changedFiles), fileSummary))
}

func reviewGateLoadConfig() map[string]any {
	home, _ := os.UserHomeDir()
	configPath := filepath.Join(home, ".claude", "data", "review-gate.json")
	data, err := os.ReadFile(configPath)
	if err != nil {
		return map[string]any{"enabled": false}
	}
	var cfg map[string]any
	if err := json.Unmarshal(data, &cfg); err != nil {
		return map[string]any{"enabled": false}
	}
	return cfg
}

func reviewGateHasCodeChanges(cwd string) (bool, []string) {
	// Try git diff HEAD first
	result := core.RunCmd(
		[]string{"git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"},
		"", 5*time.Second, cwd,
	)
	if result != nil && result.ExitCode == 0 {
		files := reviewGateParseLines(result.Stdout)
		return reviewGateFilterCodeFiles(files)
	}

	// Fallback: git status --porcelain
	result = core.RunCmd(
		[]string{"git", "status", "--porcelain", "--untracked-files=normal"},
		"", 5*time.Second, cwd,
	)
	if result == nil || strings.TrimSpace(result.Stdout) == "" {
		return false, nil
	}

	var files []string
	for _, line := range strings.Split(strings.TrimSpace(result.Stdout), "\n") {
		if len(line) > 3 {
			fname := strings.TrimSpace(line[3:])
			// Handle renames: "old -> new"
			if idx := strings.LastIndex(fname, " -> "); idx >= 0 {
				fname = fname[idx+4:]
			}
			files = append(files, fname)
		}
	}
	return reviewGateFilterCodeFiles(files)
}

func reviewGateParseLines(s string) []string {
	var result []string
	for _, line := range strings.Split(strings.TrimSpace(s), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			result = append(result, line)
		}
	}
	return result
}

func reviewGateFilterCodeFiles(files []string) (bool, []string) {
	var codeFiles []string
	for _, f := range files {
		ext := strings.ToLower(filepath.Ext(f))
		if _, ok := reviewGateCodeExts[ext]; !ok {
			continue
		}
		parts := strings.Split(strings.ReplaceAll(f, "\\", "/"), "/")
		ignored := false
		for _, p := range parts {
			if _, ok := reviewGateIgnorePatterns[p]; ok {
				ignored = true
				break
			}
		}
		if !ignored {
			codeFiles = append(codeFiles, f)
		}
	}
	return len(codeFiles) > 0, codeFiles
}

func reviewGateFileSummary(files []string) string {
	if len(files) <= 5 {
		return strings.Join(files, ", ")
	}
	return strings.Join(files[:5], ", ") + fmt.Sprintf(" (+%d more)", len(files)-5)
}
