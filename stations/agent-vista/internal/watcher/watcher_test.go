package watcher

import (
	"context"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/joneshong/agent-vista/internal/parser"
	"github.com/joneshong/agent-vista/internal/protocol"
)

// --- Mock Parser ---

type mockParser struct {
	detectResult bool
	events       []protocol.AgentEvent
}

func (m *mockParser) Detect(path string) bool { return m.detectResult }

func (m *mockParser) ParseIncremental(data []byte) ([]protocol.AgentEvent, error) {
	if len(data) == 0 {
		return nil, nil
	}
	return m.events, nil
}

func (m *mockParser) SessionInfo() protocol.SessionMeta {
	return protocol.SessionMeta{}
}

func (m *mockParser) Reset() {}

// mockFactory returns a ParserFactory that produces mockParser instances.
func mockFactory(detect bool, events []protocol.AgentEvent) ParserFactory {
	return func() parser.TranscriptParser {
		return &mockParser{
			detectResult: detect,
			events:       events,
		}
	}
}

// --- Helpers ---

// collectEvents returns a thread-safe callback and a function to drain collected events.
func collectEvents() (func(protocol.AgentEvent), func() []protocol.AgentEvent) {
	var mu sync.Mutex
	var collected []protocol.AgentEvent

	cb := func(e protocol.AgentEvent) {
		mu.Lock()
		collected = append(collected, e)
		mu.Unlock()
	}

	drain := func() []protocol.AgentEvent {
		mu.Lock()
		defer mu.Unlock()
		out := make([]protocol.AgentEvent, len(collected))
		copy(out, collected)
		return out
	}

	return cb, drain
}

// collectChan returns a callback that sends events to a channel, plus the channel.
func collectChan(size int) (func(protocol.AgentEvent), <-chan protocol.AgentEvent) {
	ch := make(chan protocol.AgentEvent, size)
	cb := func(e protocol.AgentEvent) {
		ch <- e
	}
	return cb, ch
}

// writeTempFile creates a temp file with initial content and returns its path.
func writeTempFile(t *testing.T, dir, content string) string {
	t.Helper()
	f, err := os.CreateTemp(dir, "transcript-*.jsonl")
	if err != nil {
		t.Fatalf("create temp file: %v", err)
	}
	if content != "" {
		if _, err := f.WriteString(content); err != nil {
			f.Close()
			t.Fatalf("write temp file: %v", err)
		}
	}
	name := f.Name()
	f.Close()
	return name
}

// --- Tests ---

func TestWatchFileInitialRead(t *testing.T) {
	dir := t.TempDir()
	fpath := writeTempFile(t, dir, `{"type":"message","content":"hello"}`+"\n")

	expectedEvent := protocol.AgentEvent{
		CLIType:   protocol.CLIClaude,
		SessionID: "test-session",
		EventType: protocol.EventMessage,
	}

	onEvent, drain := collectEvents()

	w, err := New(onEvent, false)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer w.Close()

	w.RegisterParserFactory(mockFactory(true, []protocol.AgentEvent{expectedEvent}))

	if err := w.WatchFile(fpath); err != nil {
		t.Fatalf("WatchFile: %v", err)
	}

	// Initial read should have produced events synchronously.
	events := drain()
	if len(events) != 1 {
		t.Fatalf("expected 1 event from initial read, got %d", len(events))
	}
	if events[0].CLIType != protocol.CLIClaude {
		t.Errorf("expected CLIType %q, got %q", protocol.CLIClaude, events[0].CLIType)
	}
	if events[0].SessionID != "test-session" {
		t.Errorf("expected SessionID %q, got %q", "test-session", events[0].SessionID)
	}
	if events[0].EventType != protocol.EventMessage {
		t.Errorf("expected EventType %q, got %q", protocol.EventMessage, events[0].EventType)
	}
}

func TestWatchFileIncrementalWrite(t *testing.T) {
	dir := t.TempDir()
	// Start with an empty file.
	fpath := writeTempFile(t, dir, "")

	expectedEvent := protocol.AgentEvent{
		CLIType:   protocol.CLICodex,
		SessionID: "incr-session",
		EventType: protocol.EventToolStart,
		ToolName:  "file_edit",
	}

	onEvent, ch := collectChan(10)

	w, err := New(onEvent, false)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer w.Close()

	w.RegisterParserFactory(mockFactory(true, []protocol.AgentEvent{expectedEvent}))

	if err := w.WatchFile(fpath); err != nil {
		t.Fatalf("WatchFile: %v", err)
	}

	// Start the event loop in the background.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go w.Start(ctx)

	// Give fsnotify a moment to set up the watch.
	time.Sleep(50 * time.Millisecond)

	// Append new content to trigger a write event.
	f, err := os.OpenFile(fpath, os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		t.Fatalf("open for append: %v", err)
	}
	_, err = f.WriteString(`{"type":"tool_start","tool":"file_edit"}` + "\n")
	f.Close()
	if err != nil {
		t.Fatalf("write append: %v", err)
	}

	// Wait for event with timeout.
	select {
	case evt := <-ch:
		if evt.CLIType != protocol.CLICodex {
			t.Errorf("expected CLIType %q, got %q", protocol.CLICodex, evt.CLIType)
		}
		if evt.EventType != protocol.EventToolStart {
			t.Errorf("expected EventType %q, got %q", protocol.EventToolStart, evt.EventType)
		}
		if evt.ToolName != "file_edit" {
			t.Errorf("expected ToolName %q, got %q", "file_edit", evt.ToolName)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for incremental write event")
	}
}

func TestWatchFileNoParser(t *testing.T) {
	dir := t.TempDir()
	fpath := writeTempFile(t, dir, "some content\n")

	onEvent, drain := collectEvents()

	w, err := New(onEvent, false)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer w.Close()

	// Register a factory that never matches.
	w.RegisterParserFactory(mockFactory(false, nil))

	// WatchFile should return nil (no error) even when no parser matches.
	if err := w.WatchFile(fpath); err != nil {
		t.Fatalf("WatchFile should not error when no parser matches: %v", err)
	}

	// No events should have been emitted.
	events := drain()
	if len(events) != 0 {
		t.Errorf("expected 0 events when no parser matches, got %d", len(events))
	}

	// The file should not be in the watched files list.
	watched := w.WatchedFiles()
	if len(watched) != 0 {
		t.Errorf("expected 0 watched files, got %d: %v", len(watched), watched)
	}
}

func TestWatchFileDuplicate(t *testing.T) {
	dir := t.TempDir()
	fpath := writeTempFile(t, dir, "line 1\n")

	expectedEvent := protocol.AgentEvent{
		CLIType:   protocol.CLIGemini,
		SessionID: "dup-session",
		EventType: protocol.EventThinking,
	}

	onEvent, drain := collectEvents()

	w, err := New(onEvent, false)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer w.Close()

	w.RegisterParserFactory(mockFactory(true, []protocol.AgentEvent{expectedEvent}))

	// First watch: should emit events from initial read.
	if err := w.WatchFile(fpath); err != nil {
		t.Fatalf("WatchFile (first): %v", err)
	}

	eventsAfterFirst := drain()
	if len(eventsAfterFirst) != 1 {
		t.Fatalf("expected 1 event from first watch, got %d", len(eventsAfterFirst))
	}

	// Second watch: should be a no-op (no additional events, no error).
	if err := w.WatchFile(fpath); err != nil {
		t.Fatalf("WatchFile (second): %v", err)
	}

	eventsAfterSecond := drain()
	// Should still be the same 1 event total (no new events from the duplicate call).
	if len(eventsAfterSecond) != 1 {
		t.Errorf("expected still 1 event after duplicate watch, got %d", len(eventsAfterSecond))
	}

	// Only one entry in watched files.
	watched := w.WatchedFiles()
	if len(watched) != 1 {
		t.Errorf("expected 1 watched file, got %d", len(watched))
	}
}

func TestWatchedFiles(t *testing.T) {
	dir := t.TempDir()

	file1 := writeTempFile(t, dir, "data1\n")
	file2 := writeTempFile(t, dir, "data2\n")
	file3 := writeTempFile(t, dir, "data3\n")

	onEvent, _ := collectEvents()

	w, err := New(onEvent, false)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer w.Close()

	w.RegisterParserFactory(mockFactory(true, []protocol.AgentEvent{
		{EventType: protocol.EventIdle},
	}))

	// Initially no watched files.
	if got := w.WatchedFiles(); len(got) != 0 {
		t.Errorf("expected 0 watched files initially, got %d", len(got))
	}

	// Watch three files.
	for _, f := range []string{file1, file2, file3} {
		if err := w.WatchFile(f); err != nil {
			t.Fatalf("WatchFile(%s): %v", f, err)
		}
	}

	watched := w.WatchedFiles()
	if len(watched) != 3 {
		t.Fatalf("expected 3 watched files, got %d", len(watched))
	}

	// Sort for deterministic comparison.
	sort.Strings(watched)
	expected := []string{file1, file2, file3}
	sort.Strings(expected)

	for i := range expected {
		// Resolve to absolute paths for comparison.
		wAbs, _ := filepath.Abs(watched[i])
		eAbs, _ := filepath.Abs(expected[i])
		if wAbs != eAbs {
			t.Errorf("watched[%d] = %q, want %q", i, watched[i], expected[i])
		}
	}
}

func TestUnwatchFile(t *testing.T) {
	dir := t.TempDir()
	fpath := writeTempFile(t, dir, "content\n")

	onEvent, _ := collectEvents()

	w, err := New(onEvent, false)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer w.Close()

	w.RegisterParserFactory(mockFactory(true, []protocol.AgentEvent{
		{EventType: protocol.EventIdle},
	}))

	if err := w.WatchFile(fpath); err != nil {
		t.Fatalf("WatchFile: %v", err)
	}

	// Verify it's being watched.
	if got := w.WatchedFiles(); len(got) != 1 {
		t.Fatalf("expected 1 watched file, got %d", len(got))
	}

	// Unwatch.
	w.UnwatchFile(fpath)

	// Verify it's no longer being watched.
	if got := w.WatchedFiles(); len(got) != 0 {
		t.Errorf("expected 0 watched files after unwatch, got %d: %v", len(got), got)
	}

	// Unwatching again should be a no-op (no panic, no error).
	w.UnwatchFile(fpath)

	if got := w.WatchedFiles(); len(got) != 0 {
		t.Errorf("expected 0 watched files after double unwatch, got %d", len(got))
	}
}
