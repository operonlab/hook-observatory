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
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

const (
	claudemdSuggestMaxPreview        = 3
	claudemdSuggestHighConfThreshold = 0.8
)

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

	oldestDays := claudemdSuggestOldestAgeDays(pending)
	highPriority := claudemdSuggestPickHighPriority(pending)

	var parts []string
	header := fmt.Sprintf("## CLAUDE.md 建議待審 (%d 條)", len(pending))
	if oldestDays > 0 {
		header += fmt.Sprintf("  ·  最舊 %d 天前", oldestDays)
	}
	parts = append(parts, header)

	if highPriority != nil {
		topic, _ := highPriority["source_topic"].(string)
		suggestion, _ := highPriority["suggestion"].(string)
		channel, _ := highPriority["target_channel"].(string)
		conf, _ := highPriority["confidence"].(float64)
		tag := ""
		if channel != "" {
			tag = fmt.Sprintf("[%s · %.2f] ", channel, conf)
		} else if topic != "" {
			tag = fmt.Sprintf("[%s] ", topic)
		}
		parts = append(parts, fmt.Sprintf("**高優先**: %s%s", tag, claudemdSuggestTruncate(suggestion, 160)))
		parts = append(parts, "")
	}

	parts = append(parts, "最近待審:")
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
		parts = append(parts, fmt.Sprintf("- %s%s", prefix, claudemdSuggestTruncate(suggestion, 120)))
	}

	if len(pending) > claudemdSuggestMaxPreview {
		parts = append(parts, fmt.Sprintf("  ... 還有 %d 條", len(pending)-claudemdSuggestMaxPreview))
	}
	parts = append(parts, "")
	parts = append(parts, "`/review-evolution` 審閱並套用（四 channel：rules / claudemd / skill-obs / memory）")
	parts = append(parts, "週報: `~/.claude/data/claudemd-suggestions/weekly-report.md`")

	return core.Message(strings.Join(parts, "\n"))
}

// claudemdSuggestPickHighPriority returns the highest-confidence refined entry
// (confidence >= 0.8) — these come from claudemd_writer.go. Returns nil if
// no refined entries exist (e.g. backlog is all legacy schema).
func claudemdSuggestPickHighPriority(rows []map[string]any) map[string]any {
	var best map[string]any
	bestConf := claudemdSuggestHighConfThreshold
	for _, r := range rows {
		conf, ok := r["confidence"].(float64)
		if !ok || conf < bestConf {
			continue
		}
		bestConf = conf
		best = r
	}
	return best
}

// claudemdSuggestOldestAgeDays returns the age (in days) of the oldest pending
// entry, or 0 if no parseable timestamps exist.
func claudemdSuggestOldestAgeDays(rows []map[string]any) int {
	now := time.Now().UTC()
	oldest := now
	found := false
	for _, r := range rows {
		ts, _ := r["timestamp"].(string)
		if ts == "" {
			continue
		}
		t, err := time.Parse(time.RFC3339, ts)
		if err != nil {
			continue
		}
		if t.Before(oldest) {
			oldest = t
			found = true
		}
	}
	if !found {
		return 0
	}
	d := int(now.Sub(oldest).Hours() / 24)
	if d < 0 {
		return 0
	}
	return d
}

func claudemdSuggestTruncate(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "..."
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
