package discovery

import (
	"context"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// TestScanOnceWithTestdata creates a temp directory mimicking the Claude
// transcript layout and verifies that discovery finds the file.
func TestScanOnceWithTestdata(t *testing.T) {
	tmpHome := t.TempDir()

	// Create Claude-style directory structure.
	convDir := filepath.Join(tmpHome, ".claude", "projects", "test-project")
	if err := os.MkdirAll(convDir, 0o755); err != nil {
		t.Fatal(err)
	}

	// Create a .jsonl transcript file with recent mtime.
	transcript := filepath.Join(convDir, "abc123.jsonl")
	if err := os.WriteFile(transcript, []byte(`{"type":"init"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	// Collect discovered paths via callback.
	var mu sync.Mutex
	var found []string
	d := New(time.Second, func(path string) {
		mu.Lock()
		defer mu.Unlock()
		found = append(found, path)
	}, false)
	// Override homeDir to use our temp directory.
	d.homeDir = tmpHome

	newPaths := d.ScanOnce()

	if len(newPaths) != 1 {
		t.Fatalf("expected 1 new path, got %d", len(newPaths))
	}
	if newPaths[0] != transcript {
		t.Errorf("expected %s, got %s", transcript, newPaths[0])
	}

	mu.Lock()
	defer mu.Unlock()
	if len(found) != 1 || found[0] != transcript {
		t.Errorf("onFound callback: expected [%s], got %v", transcript, found)
	}
}

// TestKnownSessionsDedup verifies that scanning the same file twice does not
// report it as new a second time and that KnownSessions lists it exactly once.
func TestKnownSessionsDedup(t *testing.T) {
	tmpHome := t.TempDir()

	convDir := filepath.Join(tmpHome, ".claude", "projects", "proj")
	if err := os.MkdirAll(convDir, 0o755); err != nil {
		t.Fatal(err)
	}
	transcript := filepath.Join(convDir, "sess.jsonl")
	if err := os.WriteFile(transcript, []byte(`{}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	callCount := 0
	d := New(time.Second, func(path string) {
		callCount++
	}, false)
	d.homeDir = tmpHome

	// First scan: should find the file.
	first := d.ScanOnce()
	if len(first) != 1 {
		t.Fatalf("first scan: expected 1, got %d", len(first))
	}

	// Second scan: same file should not appear as new.
	second := d.ScanOnce()
	if len(second) != 0 {
		t.Fatalf("second scan: expected 0 new, got %d", len(second))
	}

	// onFound should have been called exactly once.
	if callCount != 1 {
		t.Errorf("expected onFound called once, got %d", callCount)
	}

	// KnownSessions should contain exactly one entry.
	known := d.KnownSessions()
	if len(known) != 1 {
		t.Fatalf("expected 1 known session, got %d", len(known))
	}
	if known[0] != transcript {
		t.Errorf("expected %s, got %s", transcript, known[0])
	}
}

// TestNonExistentDirsSkipped verifies that scanning works without errors when
// none of the CLI directories exist (e.g., user has not installed a CLI).
func TestNonExistentDirsSkipped(t *testing.T) {
	tmpHome := t.TempDir()
	// tmpHome exists but contains no .claude, .codex, or .gemini dirs.

	d := New(time.Second, func(path string) {
		t.Errorf("unexpected onFound call for %s", path)
	}, false)
	d.homeDir = tmpHome

	newPaths := d.ScanOnce()
	if len(newPaths) != 0 {
		t.Fatalf("expected 0 paths from non-existent dirs, got %d", len(newPaths))
	}

	known := d.KnownSessions()
	if len(known) != 0 {
		t.Fatalf("expected 0 known sessions, got %d", len(known))
	}
}

// TestScanCodexTodayYesterday verifies that the Codex scanner looks at both
// today's and yesterday's date directories.
func TestScanCodexTodayYesterday(t *testing.T) {
	tmpHome := t.TempDir()
	now := time.Now()

	// Create today and yesterday directories.
	for _, day := range []time.Time{now, now.AddDate(0, 0, -1)} {
		dir := filepath.Join(
			tmpHome, ".codex", "sessions",
			day.Format("2006"), day.Format("01"), day.Format("02"),
		)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		f := filepath.Join(dir, "session.jsonl")
		if err := os.WriteFile(f, []byte(`{}`+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	d := New(time.Second, func(path string) {}, false)
	d.homeDir = tmpHome

	newPaths := d.ScanOnce()
	if len(newPaths) != 2 {
		t.Fatalf("expected 2 Codex sessions (today+yesterday), got %d: %v", len(newPaths), newPaths)
	}
}

// TestScanGemini verifies the Gemini scanner finds JSON files in the expected
// directory structure.
func TestScanGemini(t *testing.T) {
	tmpHome := t.TempDir()

	chatDir := filepath.Join(tmpHome, ".gemini", "tmp", "workspace1", "chats")
	if err := os.MkdirAll(chatDir, 0o755); err != nil {
		t.Fatal(err)
	}
	transcript := filepath.Join(chatDir, "chat.json")
	if err := os.WriteFile(transcript, []byte(`{}`), 0o644); err != nil {
		t.Fatal(err)
	}

	d := New(time.Second, func(path string) {}, false)
	d.homeDir = tmpHome

	newPaths := d.ScanOnce()
	if len(newPaths) != 1 {
		t.Fatalf("expected 1 Gemini session, got %d", len(newPaths))
	}
	if newPaths[0] != transcript {
		t.Errorf("expected %s, got %s", transcript, newPaths[0])
	}
}

// TestOldFilesFiltered verifies that Claude/Gemini files older than the recency
// window are NOT discovered.
func TestOldFilesFiltered(t *testing.T) {
	tmpHome := t.TempDir()

	convDir := filepath.Join(tmpHome, ".claude", "projects", "old")
	if err := os.MkdirAll(convDir, 0o755); err != nil {
		t.Fatal(err)
	}
	transcript := filepath.Join(convDir, "old.jsonl")
	if err := os.WriteFile(transcript, []byte(`{}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	// Set mtime to 2 hours ago — well outside the 30-minute window.
	oldTime := time.Now().Add(-2 * time.Hour)
	if err := os.Chtimes(transcript, oldTime, oldTime); err != nil {
		t.Fatal(err)
	}

	d := New(time.Second, func(path string) {
		t.Errorf("unexpected onFound for old file: %s", path)
	}, false)
	d.homeDir = tmpHome

	newPaths := d.ScanOnce()
	if len(newPaths) != 0 {
		t.Fatalf("expected 0 paths for old file, got %d", len(newPaths))
	}
}

// TestStartCancellation verifies that Start respects context cancellation.
func TestStartCancellation(t *testing.T) {
	tmpHome := t.TempDir()

	d := New(100*time.Millisecond, func(path string) {}, false)
	d.homeDir = tmpHome

	ctx, cancel := context.WithTimeout(context.Background(), 250*time.Millisecond)
	defer cancel()

	err := d.Start(ctx)
	if err != context.DeadlineExceeded {
		t.Errorf("expected context.DeadlineExceeded, got %v", err)
	}
}
