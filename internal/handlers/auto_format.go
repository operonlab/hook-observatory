// Package handlers — auto_format.go
// PostToolUse handler for Edit/Write events.
// Runs ruff (Python) or biome (TS/JS) after file modifications.
// Formatting must never block the agent — all errors are swallowed.
package handlers

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Edit|Write",
		Handler:    autoFormatHandle,
		Critical:   false,
		ModuleName: "auto_format",
	})
}

var autoFormatSkipDirs = map[string]struct{}{
	"node_modules": {},
	".git":         {},
	"__pycache__":  {},
	".venv":        {},
	"venv":         {},
	"dist":         {},
	"build":        {},
	".next":        {},
	".worktrees":   {},
}

var autoFormatPyExts = map[string]struct{}{
	".py": {},
}

var autoFormatJsExts = map[string]struct{}{
	".ts":  {},
	".tsx": {},
	".js":  {},
	".jsx": {},
}

func autoFormatHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Edit" && toolName != "Write" {
		return core.Allow()
	}

	rawPath, _ := toolInput["file_path"].(string)
	if rawPath == "" {
		return core.Allow()
	}

	filePath, err := filepath.EvalSymlinks(rawPath)
	if err != nil {
		filePath = rawPath
	}
	filePath, err = filepath.Abs(filePath)
	if err != nil {
		return core.Allow()
	}

	info, err := os.Stat(filePath)
	if err != nil || info.IsDir() {
		return core.Allow()
	}

	if autoFormatInSkipDir(filePath) {
		return core.Allow()
	}

	if autoFormatFindGitRoot(filePath) == "" {
		return core.Allow()
	}

	ext := strings.ToLower(filepath.Ext(filePath))

	if _, ok := autoFormatPyExts[ext]; ok {
		autoFormatPython(filePath)
	} else if _, ok := autoFormatJsExts[ext]; ok {
		autoFormatJS(filePath)
	}

	return core.Allow()
}

func autoFormatInSkipDir(filePath string) bool {
	parts := strings.Split(filePath, string(os.PathSeparator))
	for _, p := range parts {
		if _, skip := autoFormatSkipDirs[p]; skip {
			return true
		}
	}
	return false
}

func autoFormatFindGitRoot(path string) string {
	current := filepath.Dir(path)
	for {
		if _, err := os.Stat(filepath.Join(current, ".git")); err == nil {
			return current
		}
		parent := filepath.Dir(current)
		if parent == current {
			return ""
		}
		current = parent
	}
}

func autoFormatFindBiomeConfig(filePath string) string {
	current := filepath.Dir(filePath)
	for {
		for _, name := range []string{"biome.json", "biome.jsonc"} {
			if _, err := os.Stat(filepath.Join(current, name)); err == nil {
				return current
			}
		}
		parent := filepath.Dir(current)
		if parent == current {
			return ""
		}
		current = parent
	}
}

func autoFormatFindBiomeBin(configDir string) string {
	localBin := filepath.Join(configDir, "node_modules", ".bin", "biome")
	if info, err := os.Stat(localBin); err == nil && !info.IsDir() {
		return localBin
	}
	p, err := exec.LookPath("biome")
	if err == nil {
		return p
	}
	return ""
}

func autoFormatPython(filePath string) {
	ruffBin := core.Cfg().GetTool("ruff")
	if ruffBin == "" {
		return
	}
	if _, err := os.Stat(ruffBin); err != nil {
		return
	}
	// ruff check --fix --silent
	core.RunCmd([]string{ruffBin, "check", "--fix", "--silent", filePath}, "", 15*time.Second, "")
	// ruff format --quiet
	core.RunCmd([]string{ruffBin, "format", "--quiet", filePath}, "", 15*time.Second, "")
}

func autoFormatJS(filePath string) {
	configDir := autoFormatFindBiomeConfig(filePath)
	if configDir == "" {
		return
	}
	biomeBin := autoFormatFindBiomeBin(configDir)
	if biomeBin == "" {
		return
	}
	core.RunCmd(
		[]string{biomeBin, "check", "--write", "--no-errors-on-unmatched", filePath},
		"", 15*time.Second, configDir,
	)
}
