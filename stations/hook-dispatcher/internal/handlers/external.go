package handlers

// external.go — Go port of handlers/external.py
//
// Wraps four sub-handlers that call external scripts:
//   - recall        → UserPromptSubmit  (memvault recall)
//   - skill_tracker → PostToolUse/Skill (skill usage tracker)
//   - progressive_extract → PreCompact  (fire-and-forget extraction)
//   - sync_login    → SessionStart      (Playwright profile sync)
//
// All are deferrable. Any error → fail-open (core.Allow()).

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("UserPromptSubmit", core.Entry{
		Matcher:    "",
		Handler:    externalRecall,
		Critical:   false,
		ModuleName: "external",
	})
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Skill",
		Handler:    externalSkillTracker,
		Critical:   false,
		ModuleName: "external",
	})
	core.Register("PreCompact", core.Entry{
		Matcher:    "",
		Handler:    externalProgressiveExtract,
		Critical:   false,
		ModuleName: "external",
	})
	core.Register("SessionStart", core.Entry{
		Matcher:    "",
		Handler:    externalSyncLogin,
		Critical:   false,
		ModuleName: "external",
	})
}

func memvaultScripts() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "workshop", "mcp", "memvault", "scripts")
}

// externalRecall runs the memvault recall.py script and returns its output
// as a UserPromptSubmit text injection.
func externalRecall(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	script := filepath.Join(memvaultScripts(), "recall.py")
	python := pythonBin()
	r := core.RunCmd([]string{python, script}, rawInput, 15*time.Second, "")
	if r == nil || r.ExitCode != 0 {
		return core.Allow()
	}
	out := r.Stdout
	if out == "" {
		return core.Allow()
	}
	return core.TextResult(out)
}

// externalSkillTracker runs skill_tracker.py fire-and-forget style.
func externalSkillTracker(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	script := filepath.Join(memvaultScripts(), "skill_tracker.py")
	python := pythonBin()
	if _, err := os.Stat(script); err != nil {
		return core.Allow()
	}
	_ = core.RunBackground([]string{
		"sh", "-c",
		fmt.Sprintf("echo %s | %s %s", shellQuote(rawInput), python, shellQuote(script)),
	}, "")
	return core.Allow()
}

// externalProgressiveExtract writes rawInput to a temp file and runs
// extract_progressive.py in the background (fire-and-forget, PreCompact).
func externalProgressiveExtract(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	script := filepath.Join(memvaultScripts(), "extract_progressive.py")
	if _, err := os.Stat(script); err != nil {
		return core.Allow()
	}

	// Write rawInput to temp file — background process reads it.
	tmpf, err := os.CreateTemp("/tmp", "memvault-prog-*.json")
	if err != nil {
		return core.Allow()
	}
	tmpPath := tmpf.Name()
	if _, err := tmpf.WriteString(rawInput); err != nil {
		_ = tmpf.Close()
		_ = os.Remove(tmpPath)
		return core.Allow()
	}
	_ = tmpf.Close()

	python := pythonBin()
	_ = core.RunBackground([]string{
		"sh", "-c",
		fmt.Sprintf("cat %s | %s %s; rm -f %s",
			shellQuote(tmpPath), python, shellQuote(script), shellQuote(tmpPath)),
	}, "")

	return core.Allow()
}

// externalSyncLogin runs ~/.playwright-profiles/sync-login.sh --hook.
func externalSyncLogin(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	home, _ := os.UserHomeDir()
	script := filepath.Join(home, ".playwright-profiles", "sync-login.sh")
	if _, err := os.Stat(script); err != nil {
		return core.Allow()
	}
	r := core.RunCmd([]string{script, "--hook"}, rawInput, 15*time.Second, "")
	if r == nil || r.ExitCode != 0 {
		return core.Allow()
	}
	return core.Allow()
}

// --- helpers -----------------------------------------------------------------

// pythonBin returns the canonical python3 path for this workshop.
func pythonBin() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".local", "bin", "python3")
}

// shellQuote wraps s in single quotes, escaping any embedded single quotes.
func shellQuote(s string) string {
	result := "'"
	for _, ch := range s {
		if ch == '\'' {
			result += "'\\''"
		} else {
			result += string(ch)
		}
	}
	result += "'"
	return result
}
