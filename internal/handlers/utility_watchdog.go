package handlers

// utility_watchdog.go — Go port of handlers/utility_watchdog.py
//
// SessionEnd: spawn background utility_check.py for the just-ended session.
// SessionStart: read proposals.jsonl + create-proposals.jsonl and emit a
//
//	reminder message if enough proposals have accumulated.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const (
	uwProposalThreshold = 3       // min proposals per skill before alerting
	uwCreateThreshold   = 5       // min create-proposal lines before alerting
	uwMaxFileSize       = 100_000 // bytes — truncate beyond this
)

func init() {
	entry := core.Entry{
		Matcher:    "",
		Handler:    utilityWatchdogHandle,
		Critical:   false,
		ModuleName: "utility_watchdog",
	}
	core.Register("SessionEnd", entry)
	core.Register("SessionStart", entry)
}

func utilityWatchdogHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	switch eventType {
	case "SessionEnd":
		return uwHandleSessionEnd(rawInput)
	case "SessionStart":
		return uwHandleSessionStart()
	default:
		return core.Allow()
	}
}

// ---------------------------------------------------------------------------
// SessionEnd: spawn background utility check
// ---------------------------------------------------------------------------

func uwHandleSessionEnd(rawInput string) core.HookResult {
	var data map[string]any
	if rawInput != "" {
		if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
			return core.Allow()
		}
	}

	sessionID, _ := data["session_id"].(string)
	if sessionID == "" {
		return core.Allow()
	}

	dataDir := uwDataDir()
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return core.Allow()
	}

	home, _ := os.UserHomeDir()
	checkScript := filepath.Join(home, "workshop", "stations", "anvil", "scripts", "utility_check.py")
	python := core.Cfg().GetTool("python")
	if python == "" {
		python = filepath.Join(home, ".local", "bin", "python3")
	}

	// Detached background — same pattern as Python subprocess.Popen(start_new_session=True)
	_ = core.RunBackground([]string{python, checkScript, sessionID}, "")
	return core.Allow()
}

// ---------------------------------------------------------------------------
// SessionStart: inject reminder if proposals have accumulated
// ---------------------------------------------------------------------------

func uwHandleSessionStart() core.HookResult {
	dataDir := uwDataDir()
	proposalsFile := filepath.Join(dataDir, "proposals.jsonl")
	createFile := filepath.Join(dataDir, "create-proposals.jsonl")

	var messages []string

	// 1. Utility proposals
	if info, err := os.Stat(proposalsFile); err == nil {
		if info.Size() > uwMaxFileSize {
			_ = os.WriteFile(proposalsFile, []byte(""), 0o644)
			return core.Allow()
		}

		raw, err := os.ReadFile(proposalsFile)
		if err == nil {
			skillCounts := map[string][]map[string]any{}
			for _, line := range strings.Split(string(raw), "\n") {
				line = strings.TrimSpace(line)
				if line == "" {
					continue
				}
				var entry map[string]any
				if err := json.Unmarshal([]byte(line), &entry); err != nil {
					continue
				}
				name, _ := entry["skill_name"].(string)
				if name != "" {
					skillCounts[name] = append(skillCounts[name], entry)
				}
			}

			flagged := map[string]any{}
			for name, entries := range skillCounts {
				if len(entries) >= uwProposalThreshold {
					latest := entries[len(entries)-1]
					flagged[name] = latest["utility"]
				}
			}

			if len(flagged) > 0 {
				parts := make([]string, 0, len(flagged))
				for name, score := range flagged {
					scoreStr := "?"
					if score != nil {
						b, _ := json.Marshal(score)
						scoreStr = strings.Trim(string(b), `"`)
					}
					parts = append(parts, name+"("+scoreStr+")")
				}
				messages = append(messages,
					"[Utility Watchdog] "+itoa(len(flagged))+" skills below threshold: "+
						strings.Join(parts, ", ")+". Consider /skill-optimizer.",
				)

				// Clean up: remove alerted skills
				var remaining []string
				for name, entries := range skillCounts {
					if _, wasFlagged := flagged[name]; !wasFlagged {
						for _, e := range entries {
							b, _ := json.Marshal(e)
							remaining = append(remaining, string(b))
						}
					}
				}
				newContent := ""
				if len(remaining) > 0 {
					newContent = strings.Join(remaining, "\n") + "\n"
				}
				_ = os.WriteFile(proposalsFile, []byte(newContent), 0o644)
			}
		}
	}

	// 2. CreateOnMiss proposals
	if info, err := os.Stat(createFile); err == nil {
		if info.Size() > uwMaxFileSize {
			_ = os.WriteFile(createFile, []byte(""), 0o644)
			return core.Allow()
		}

		raw, err := os.ReadFile(createFile)
		if err == nil {
			var createLines []string
			for _, line := range strings.Split(string(raw), "\n") {
				if strings.TrimSpace(line) != "" {
					createLines = append(createLines, line)
				}
			}
			if len(createLines) >= uwCreateThreshold {
				messages = append(messages,
					"[CreateOnMiss] "+itoa(len(createLines))+" sessions completed without skills. Consider /create-skill.",
				)
				_ = os.WriteFile(createFile, []byte(""), 0o644)
			}
		}
	}

	if len(messages) > 0 {
		return core.Message(strings.Join(messages, " | "))
	}
	return core.Allow()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func uwDataDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude", "data", "utility-watchdog")
}

// Note: itoa() is defined in secret_scan.go (same package).
