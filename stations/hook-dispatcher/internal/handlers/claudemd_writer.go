// Package handlers — claudemd_writer.go
// SessionEnd handler — promotes raw-blocks.jsonl entries to pending.jsonl
// via Haiku reflection (refines phrasing + classifies target channel).
//
// Two-stage architecture:
//
//	extract.py writes raw-blocks.jsonl  (fact layer, dual-write with pending)
//	             ↓ 120s delayed
//	claudemd_writer.go (this file)      (reflection + classification)
//	             ↓
//	pending.jsonl                       (reviewable, consumed by /review-evolution)
//
// Non-blocking: spawns goroutine, returns Allow immediately.
// Fail-open: any error -> log + skip, never block Claude Code.
//
// First-cut implementation: no embedding-based dedup yet (planned Phase 3.5).
// Relies on extract.py prefilter + /review-evolution batch review to handle dups.
package handlers

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const (
	claudemdWriterDelay   = 120 * time.Second
	claudemdWriterTimeout = 60 * time.Second
	claudemdWriterMaxRaw  = 50 // safety cap per session
)

var claudemdWriterValidChannels = map[string]struct{}{
	"claudemd-global":  {},
	"claudemd-project": {},
	"rules":            {},
	"skill-obs":        {},
	"memory-topic":     {},
}

func init() {
	core.Register("SessionEnd", core.Entry{
		Matcher:    "",
		Handler:    claudemdWriterHandle,
		Critical:   false,
		ModuleName: "claudemd_writer",
	})
}

func claudemdWriterHandle(_, _ string, _ map[string]any, _ string) core.HookResult {
	if os.Getenv("CLAUDEMD_WRITER") == "0" {
		return core.Allow()
	}
	go claudemdWriterRun()
	return core.Allow()
}

func claudemdWriterRun() {
	// Delay so extract.py finishes writing raw-blocks.jsonl
	time.Sleep(claudemdWriterDelay)

	home, err := os.UserHomeDir()
	if err != nil {
		return
	}
	stagingDir := filepath.Join(home, ".claude", "data", "claudemd-suggestions")
	rawPath := filepath.Join(stagingDir, "raw-blocks.jsonl")
	cursorPath := filepath.Join(stagingDir, "processed-cursor.txt")
	pendingPath := filepath.Join(stagingDir, "pending.jsonl")
	rejectedPath := filepath.Join(stagingDir, "dedup-rejected.jsonl")

	cursor := claudemdWriterReadCursor(cursorPath)

	entries, newCursor := claudemdWriterReadNewRaw(rawPath, cursor)
	if len(entries) == 0 {
		return
	}
	if len(entries) > claudemdWriterMaxRaw {
		// Cap to avoid burning Haiku tokens on a single mega session
		entries = entries[:claudemdWriterMaxRaw]
	}

	pendingFile, err := os.OpenFile(pendingPath, os.O_RDWR|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	defer pendingFile.Close()

	// Lock the pending file for the whole batch to avoid interleaving with
	// review-evolution or other writers.
	if err := syscall.Flock(int(pendingFile.Fd()), syscall.LOCK_EX); err != nil {
		return
	}
	defer syscall.Flock(int(pendingFile.Fd()), syscall.LOCK_UN) //nolint:errcheck

	written := 0
	for _, entry := range entries {
		reflected := claudemdWriterReflect(entry)
		if reflected == nil {
			continue
		}
		if reason, _ := reflected["discard_reason"].(string); strings.TrimSpace(reason) != "" {
			// Log to rejected pile for audit (best-effort)
			_ = claudemdWriterAppendJSONL(rejectedPath, reflected)
			continue
		}
		if line, err := json.Marshal(reflected); err == nil {
			pendingFile.Write(line)
			pendingFile.Write([]byte("\n"))
			written++
		}
	}

	// Update cursor only after a successful pass (even if 0 written — entries were
	// considered). On error before this point, cursor stays put and we retry next time.
	claudemdWriterWriteCursor(cursorPath, newCursor)

	_ = written // (telemetry hook later — currently silent on success)
}

// claudemdWriterReadCursor returns the byte offset into raw-blocks.jsonl that
// has been processed. Defaults to 0 (process from start) if missing.
func claudemdWriterReadCursor(path string) int64 {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	n, err := strconv.ParseInt(strings.TrimSpace(string(data)), 10, 64)
	if err != nil {
		return 0
	}
	return n
}

func claudemdWriterWriteCursor(path string, offset int64) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	_ = os.WriteFile(path, []byte(strconv.FormatInt(offset, 10)), 0o644)
}

// claudemdWriterReadNewRaw streams raw-blocks.jsonl from offset, returning
// new entries and the resulting offset.
func claudemdWriterReadNewRaw(path string, cursor int64) ([]map[string]any, int64) {
	f, err := os.Open(path)
	if err != nil {
		return nil, cursor
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		return nil, cursor
	}
	if info.Size() < cursor {
		// File was truncated/rotated — reset cursor to start
		cursor = 0
	}
	if _, err := f.Seek(cursor, 0); err != nil {
		return nil, cursor
	}

	var entries []map[string]any
	scanner := bufio.NewScanner(f)
	// Allow longer lines (default 64KB may not be enough for some suggestions)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err == nil {
			entries = append(entries, entry)
		}
	}
	endOffset := info.Size()
	return entries, endOffset
}

// claudemdWriterReflect runs Haiku to upgrade a raw block into a structured
// CLAUDE.md suggestion. Returns nil on any failure (fail-open).
func claudemdWriterReflect(raw map[string]any) map[string]any {
	rawSuggestion, _ := raw["suggestion"].(string)
	rawTopic, _ := raw["source_topic"].(string)
	rawSuggestion = strings.TrimSpace(rawSuggestion)
	rawTopic = strings.TrimSpace(rawTopic)
	if rawSuggestion == "" {
		return nil
	}

	prompt := claudemdWriterBuildPrompt(rawTopic, rawSuggestion)

	env := os.Environ()
	env = sessionNamerReplaceEnv(env, "CTX_SUPERVISOR_LEVEL", "off")
	env = sessionNamerReplaceEnv(env, "CLAUDEMD_WRITER", "0")
	env = sessionNamerReplaceEnv(env, "CLAUDE_SESSION_NAMER", "0")

	r := core.RunCmdWithEnv(
		[]string{"claude", "-p", prompt, "--model", "haiku", "--output-format", "text", "--no-session-persistence"},
		"", claudemdWriterTimeout, "", env,
	)
	if r == nil || r.ExitCode != 0 {
		return nil
	}

	parsed := claudemdWriterParseJSON(r.Stdout)
	if parsed == nil {
		return nil
	}

	// Validate channel
	channel, _ := parsed["target_channel"].(string)
	if _, ok := claudemdWriterValidChannels[channel]; !ok {
		// Unknown channel — degrade to rules (most generic)
		parsed["target_channel"] = "rules"
		parsed["_channel_invalid"] = channel
	}

	// Validate confidence
	confRaw, _ := parsed["confidence"].(float64)
	if confRaw < 0 || confRaw > 1 {
		confRaw = 0.5
	}

	// Compose the final pending entry: preserve original metadata, add refined
	// fields. Schema is intentionally a superset of legacy pending.jsonl so
	// /review-evolution & claudemd_suggest.go reader don't need changes.
	refined, _ := parsed["suggestion"].(string)
	refined = strings.TrimSpace(refined)
	if refined == "" {
		refined = rawSuggestion
	}

	now := time.Now().UTC().Format("2006-01-02T15:04:05Z")
	timestamp, _ := raw["timestamp"].(string)
	if timestamp == "" {
		timestamp = now
	}
	sessionID, _ := raw["session_id"].(string)
	project, _ := raw["project"].(string)

	out := map[string]any{
		"timestamp":      timestamp,
		"session_id":     sessionID,
		"project":        project,
		"suggestion":     refined,
		"source_topic":   rawTopic,
		"reviewed":       false,
		"target_channel": parsed["target_channel"],
		"target_hint":    parsed["target_hint"],
		"confidence":     confRaw,
		"refined_at":     now,
	}
	if reason, _ := parsed["discard_reason"].(string); strings.TrimSpace(reason) != "" {
		out["discard_reason"] = strings.TrimSpace(reason)
	}
	return out
}

func claudemdWriterBuildPrompt(topic, raw string) string {
	return `Below is a candidate CLAUDE.md suggestion auto-extracted from a Claude Code session.
Improve it into a concrete, actionable rule.

Channels:
- claudemd-global: cross-project personal preference / env
- claudemd-project: workshop-specific convention
- rules: gotcha for a tool/CLI/env
- skill-obs: skill-specific behavior observation
- memory-topic: cross-session technical fact

Return JSON only:
{
  "suggestion": "<rewritten as actionable rule, max 200 chars>",
  "target_channel": "<one of the 5 channels above>",
  "target_hint": "<file or skill name suggestion, optional>",
  "confidence": 0.0-1.0,
  "discard_reason": "<reason or empty>"
}

If the suggestion is trivial/noise, set discard_reason and confidence=0.
Do not invent details not present in the raw suggestion.

Source topic: ` + topic + `
Raw suggestion: ` + raw
}

func claudemdWriterParseJSON(stdout string) map[string]any {
	raw := strings.TrimSpace(stdout)
	if raw == "" {
		return nil
	}
	// Try direct parse first
	var parsed map[string]any
	if err := json.Unmarshal([]byte(raw), &parsed); err == nil {
		return parsed
	}
	// Fallback: extract first JSON object via regex (handles preamble text)
	jsonPat := regexp.MustCompile(`(?s)\{.*?"target_channel".*?\}`)
	if m := jsonPat.FindString(raw); m != "" {
		if err := json.Unmarshal([]byte(m), &parsed); err == nil {
			return parsed
		}
	}
	return nil
}

func claudemdWriterAppendJSONL(path string, entry map[string]any) error {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	if line, err := json.Marshal(entry); err == nil {
		fmt.Fprintln(f, string(line))
	}
	return nil
}
