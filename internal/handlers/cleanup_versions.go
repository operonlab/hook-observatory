// Package handlers — cleanup_versions.go
// SessionStart handler.
// Scans ~/.local/share/claude/versions/, keeps the current version
// (symlink target of ~/.local/bin/claude), deletes the rest.
package handlers

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	core.Register("SessionStart", core.Entry{
		Matcher:    "",
		Handler:    cleanupVersionsHandle,
		Critical:   false,
		ModuleName: "cleanup_versions",
	})
}

func cleanupVersionsHandle(_, _ string, _ map[string]any, _ string) core.HookResult {
	home, err := os.UserHomeDir()
	if err != nil {
		return core.Allow()
	}

	versionsDir := filepath.Join(home, ".local", "share", "claude", "versions")
	claudeBin := filepath.Join(home, ".local", "bin", "claude")

	if _, err := os.Stat(versionsDir); err != nil {
		return core.Message("no versions directory found")
	}

	current, _ := filepath.EvalSymlinks(claudeBin)

	entries, err := os.ReadDir(versionsDir)
	if err != nil {
		return core.Allow()
	}

	removed := 0
	var freedParts []string

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		path := filepath.Join(versionsDir, entry.Name())
		if path == current {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		size := info.Size()
		if err := os.Remove(path); err != nil {
			continue
		}
		removed++
		freedParts = append(freedParts, cleanupVersionsHumanSize(size))
	}

	if removed > 0 {
		freed := strings.Join(freedParts, " ")
		return core.Message(fmt.Sprintf("cleaned %d old versions (freed %s)", removed, freed))
	}
	return core.Message("no old versions to clean")
}

func cleanupVersionsHumanSize(nbytes int64) string {
	units := []string{"B", "K", "M", "G"}
	f := float64(nbytes)
	for _, unit := range units {
		if f < 1024 {
			return fmt.Sprintf("%.0f%s", f, unit)
		}
		f /= 1024
	}
	return fmt.Sprintf("%.0fT", f)
}
