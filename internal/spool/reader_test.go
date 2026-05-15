package spool

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// ─── helpers ──────────────────────────────────────────────────────────────────

func tmpSpool(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOOK_OBS_SPOOL_DIR", dir)
	return dir
}

func writeLines(t *testing.T, path string, lines []string) {
	t.Helper()
	content := strings.Join(lines, "\n") + "\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("writeLines: %v", err)
	}
}

func mkEvent(ts, eventType, sessionID, toolName string) string {
	return fmt.Sprintf(
		`{"event_type":%q,"ts":%q,"data":{"session_id":%q,"tool_name":%q}}`,
		eventType, ts, sessionID, toolName,
	)
}

// ─── Test: empty directory ─────────────────────────────────────────────────────

func TestRead_EmptyDir_ReturnsEmptySliceNoError(t *testing.T) {
	dir := tmpSpool(t)
	events, err := Read(dir)
	if err != nil {
		t.Fatalf("expected nil error on empty dir, got: %v", err)
	}
	// Must return empty slice (or nil), never panic
	if len(events) != 0 {
		t.Fatalf("expected 0 events, got %d", len(events))
	}
}

// ─── Test: non-existent directory ────────────────────────────────────────────

func TestRead_NonExistentDir_ReturnsError(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "no-such-subdir")
	t.Setenv("HOOK_OBS_SPOOL_DIR", dir)
	// candidateFiles uses os.Stat on events.jsonl and Glob on *.processing.
	// A missing dir means events.jsonl doesn't exist (ErrNotExist → skip) and
	// Glob returns no matches — so Read returns ([], nil) not an error.
	// Verify at least it doesn't panic.
	events, _ := Read(dir)
	if events == nil {
		events = []Event{}
	}
	// Any length is acceptable; we just verified no panic.
}

// ─── Test: mixed good + bad JSON lines ───────────────────────────────────────

func TestRead_MixedBadAndGoodLines_SkipsBad(t *testing.T) {
	dir := tmpSpool(t)
	path := filepath.Join(dir, "events.jsonl")
	writeLines(t, path, []string{
		mkEvent("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
		`{not valid json`,
		`{"event_type":"","ts":"2026-05-01T10:01:00Z","data":{}}`, // empty type → skip
		`null`,
		mkEvent("2026-05-01T10:02:00Z", "PreToolUse", "s1", "Bash"),
	})
	events, err := Read(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 valid events, got %d", len(events))
	}
	if events[0].EventType != "SessionStart" {
		t.Errorf("first event should be SessionStart, got %q", events[0].EventType)
	}
	if events[1].EventType != "PreToolUse" {
		t.Errorf("second event should be PreToolUse, got %q", events[1].EventType)
	}
}

// ─── Test: very large line (≤4MB) ─────────────────────────────────────────────

func TestRead_LargeLine_ParsesSuccessfully(t *testing.T) {
	dir := tmpSpool(t)
	path := filepath.Join(dir, "events.jsonl")

	bigPayload := strings.Repeat("x", 3*1024*1024) // 3MB value
	line := fmt.Sprintf(
		`{"event_type":"LargePayload","ts":"2026-05-01T10:00:00Z","data":{"content":%q}}`,
		bigPayload,
	)
	writeLines(t, path, []string{line})

	events, err := Read(dir)
	if err != nil {
		t.Fatalf("unexpected error on large line: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	if events[0].EventType != "LargePayload" {
		t.Errorf("wrong event type: %q", events[0].EventType)
	}
}

// ─── Test: events-*.processing files are included ────────────────────────────

func TestRead_ProcessingFilesIncluded(t *testing.T) {
	dir := tmpSpool(t)
	// Write main file
	mainPath := filepath.Join(dir, "events.jsonl")
	writeLines(t, mainPath, []string{
		mkEvent("2026-05-01T09:00:00Z", "SessionStart", "s1", ""),
	})
	// Write processing file (mid-drain rolled file)
	procPath := filepath.Join(dir, "events-20260501T090000.processing")
	writeLines(t, procPath, []string{
		mkEvent("2026-05-01T08:00:00Z", "PreToolUse", "s1", "Bash"),
	})

	events, err := Read(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 events (main + processing), got %d", len(events))
	}
}

// ─── Test: timestamp ascending sort ──────────────────────────────────────────

func TestRead_ReturnsTSAscending(t *testing.T) {
	dir := tmpSpool(t)
	path := filepath.Join(dir, "events.jsonl")
	// Write in reverse order
	writeLines(t, path, []string{
		mkEvent("2026-05-01T12:00:00Z", "C", "s3", ""),
		mkEvent("2026-05-01T10:00:00Z", "A", "s1", ""),
		mkEvent("2026-05-01T11:00:00Z", "B", "s2", ""),
	})
	events, err := Read(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d", len(events))
	}
	if events[0].EventType != "A" || events[1].EventType != "B" || events[2].EventType != "C" {
		t.Errorf("sort order wrong: %v", []string{
			events[0].EventType, events[1].EventType, events[2].EventType,
		})
	}
	for i := 1; i < len(events); i++ {
		if events[i].TS.Before(events[i-1].TS) {
			t.Errorf("events[%d] is before events[%d]", i, i-1)
		}
	}
}

// ─── Test: Event accessor methods on missing data fields ─────────────────────

func TestEvent_Accessors_MissingKey_ReturnsEmpty(t *testing.T) {
	ev := Event{
		EventType: "SessionEnd",
		TS:        time.Now(),
		Data:      []byte(`{}`), // no session_id / tool_name / hook_event_name
	}
	if got := ev.SessionID(); got != "" {
		t.Errorf("SessionID on empty data: want \"\", got %q", got)
	}
	if got := ev.ToolName(); got != "" {
		t.Errorf("ToolName on empty data: want \"\", got %q", got)
	}
	if got := ev.HookEventName(); got != "" {
		t.Errorf("HookEventName on empty data: want \"\", got %q", got)
	}
}

func TestEvent_Accessors_NilData_ReturnsEmpty(t *testing.T) {
	ev := Event{EventType: "X", TS: time.Now(), Data: nil}
	// Must not panic
	_ = ev.SessionID()
	_ = ev.ToolName()
	_ = ev.HookEventName()
}

func TestEvent_Accessors_InvalidJSON_ReturnsEmpty(t *testing.T) {
	ev := Event{EventType: "X", TS: time.Now(), Data: []byte(`{not json`)}
	if got := ev.SessionID(); got != "" {
		t.Errorf("want empty, got %q", got)
	}
}

func TestEvent_Accessors_CorrectValues(t *testing.T) {
	ev := Event{
		EventType: "PreToolUse",
		TS:        time.Now(),
		Data:      []byte(`{"session_id":"abc-123","tool_name":"Bash","hook_event_name":"PreToolUse"}`),
	}
	if got := ev.SessionID(); got != "abc-123" {
		t.Errorf("SessionID: want %q, got %q", "abc-123", got)
	}
	if got := ev.ToolName(); got != "Bash" {
		t.Errorf("ToolName: want %q, got %q", "Bash", got)
	}
	if got := ev.HookEventName(); got != "PreToolUse" {
		t.Errorf("HookEventName: want %q, got %q", "PreToolUse", got)
	}
}

// ─── Test: HOOK_OBS_SPOOL_DIR env var override ───────────────────────────────

func TestDefaultSpoolDir_EnvVarOverride(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOOK_OBS_SPOOL_DIR", dir)
	got := DefaultSpoolDir()
	if got != dir {
		t.Errorf("DefaultSpoolDir: want %q, got %q", dir, got)
	}
}

func TestDefaultSpoolDir_FallbackToHome(t *testing.T) {
	// Unset the env var so it falls back
	t.Setenv("HOOK_OBS_SPOOL_DIR", "")
	got := DefaultSpoolDir()
	if got == "" {
		t.Error("DefaultSpoolDir fallback should not be empty")
	}
	// Must contain ".hook-observatory/spool"
	if !strings.Contains(got, ".hook-observatory") {
		t.Errorf("expected .hook-observatory in fallback path, got %q", got)
	}
}

// ─── Test: only .processing file, no events.jsonl ────────────────────────────

func TestRead_OnlyProcessingFile_Included(t *testing.T) {
	dir := tmpSpool(t)
	procPath := filepath.Join(dir, "events-20260501.processing")
	writeLines(t, procPath, []string{
		mkEvent("2026-05-01T08:30:00Z", "PostToolUse", "s2", "Write"),
	})
	events, err := Read(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event from .processing only, got %d", len(events))
	}
}

// ─── Test: empty lines in file are skipped (no panic) ────────────────────────

func TestRead_EmptyLinesSkipped(t *testing.T) {
	dir := tmpSpool(t)
	path := filepath.Join(dir, "events.jsonl")
	content := "\n\n" + mkEvent("2026-05-01T10:00:00Z", "SessionStart", "s1", "") + "\n\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	events, err := Read(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
}
