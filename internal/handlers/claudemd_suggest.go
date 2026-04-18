// Package handlers — claudemd_suggest.go
// SessionStart handler.
// Reads pending CLAUDE.md suggestions from staging JSONL and notifies user.
package handlers

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const claudemdSuggestMaxPreview = 3

func init() {
	core.Register("SessionStart", core.Entry{
		Matcher:    "",
		Handler:    claudemdSuggestHandle,
		Critical:   false,
		ModuleName: "claudemd_suggest",
	})
}

func claudemdSuggestHandle(eventType, _ string, _ map[string]any, _ string) core.HookResult {
	if eventType != "SessionStart" {
		return core.Allow()
	}

	pending := claudemdSuggestLoadPending()
	if len(pending) == 0 {
		return core.Allow()
	}

	var parts []string
	parts = append(parts, fmt.Sprintf("## CLAUDE.md 建議待審 (%d 條)", len(pending)))

	limit := claudemdSuggestMaxPreview
	if len(pending) < limit {
		limit = len(pending)
	}
	for _, entry := range pending[:limit] {
		topic, _ := entry["source_topic"].(string)
		suggestion, _ := entry["suggestion"].(string)
		prefix := ""
		if topic != "" {
			prefix = fmt.Sprintf("[%s] ", topic)
		}
		parts = append(parts, fmt.Sprintf("- %s%s", prefix, suggestion))
	}

	if len(pending) > claudemdSuggestMaxPreview {
		parts = append(parts, fmt.Sprintf("  ... 還有 %d 條", len(pending)-claudemdSuggestMaxPreview))
	}
	parts = append(parts, "使用 `/review-claudemd` 審閱並套用")

	return core.Message(strings.Join(parts, "\n"))
}

func claudemdSuggestLoadPending() []map[string]any {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil
	}
	stagingFile := filepath.Join(home, ".claude", "data", "claudemd-suggestions", "pending.jsonl")

	f, err := os.Open(stagingFile)
	if err != nil {
		return nil
	}
	defer f.Close()

	var entries []map[string]any
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		reviewed, _ := entry["reviewed"].(bool)
		if !reviewed {
			entries = append(entries, entry)
		}
	}
	return entries
}
