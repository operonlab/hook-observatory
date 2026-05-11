package handlers

// Layer 2: 資料流測試 — pre_compact
// 測「多函數串起來」的場景：
// - 同一 session_id 連續 2 次 dispatch → 第二次 overwrite 第一次，無垃圾殘留
// - 不同 session_id 各自寫各自的 checkpoint，不互相干擾
// - dispatcher 回傳 message 含 PreCompact 字樣 (hint 合約)

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

// TestPreCompactDataflow_DoubleDispatchOverwrites verifies that dispatching
// PreCompact twice with the same session_id results in exactly one checkpoint
// file whose content reflects the latest write.
func TestPreCompactDataflow_DoubleDispatchOverwrites(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	core.Reset()
	RegisterPreCompact()

	first := `{"session_id":"double-sess","trigger":"auto","cwd":"/first"}`
	second := `{"session_id":"double-sess","trigger":"manual","cwd":"/second"}`

	_ = core.Dispatch("PreCompact", first)
	_ = core.Dispatch("PreCompact", second)

	// Exactly one file should exist.
	dir := filepath.Join(home, ".claude", "data", "pre-compact")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("ReadDir: %v", err)
	}

	sessionFiles := 0
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), "double-sess.json") {
			sessionFiles++
		}
	}
	if sessionFiles != 1 {
		t.Errorf("expected 1 checkpoint file, found %d", sessionFiles)
	}

	// Content must reflect the second write.
	cp, ok := readCheckpoint(t, home, "double-sess")
	if !ok {
		t.Fatal("checkpoint file not found")
	}
	if cp.Cwd != "/second" {
		t.Errorf("latest-wins failed: Cwd=%q want %q", cp.Cwd, "/second")
	}
	if cp.Trigger != "manual" {
		t.Errorf("latest-wins failed: Trigger=%q want 'manual'", cp.Trigger)
	}
}

// TestPreCompactDataflow_DifferentSessionsIsolated verifies that dispatching
// PreCompact for two different sessions creates two independent checkpoint
// files without contamination.
func TestPreCompactDataflow_DifferentSessionsIsolated(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	core.Reset()
	RegisterPreCompact()

	payloads := []struct {
		raw string
		id  string
		cwd string
	}{
		{`{"session_id":"sess-alpha","trigger":"auto","cwd":"/alpha"}`, "sess-alpha", "/alpha"},
		{`{"session_id":"sess-beta","trigger":"manual","cwd":"/beta"}`, "sess-beta", "/beta"},
	}

	for _, p := range payloads {
		_ = core.Dispatch("PreCompact", p.raw)
	}

	for _, p := range payloads {
		cp, ok := readCheckpoint(t, home, p.id)
		if !ok {
			t.Errorf("checkpoint not found for session %q", p.id)
			continue
		}
		if cp.Cwd != p.cwd {
			t.Errorf("session %q: Cwd=%q want %q", p.id, cp.Cwd, p.cwd)
		}
	}
}

// TestPreCompactDataflow_HintMessageContract verifies the full dispatch→output
// pipeline: the handler must return valid JSON with a non-empty "message" field
// that references "PreCompact" (the hint injected into Claude's context).
func TestPreCompactDataflow_HintMessageContract(t *testing.T) {
	_, cleanup := setupPreCompactHome(t)
	defer cleanup()

	core.Reset()
	RegisterPreCompact()

	raw := `{"session_id":"hint-test","trigger":"auto","cwd":"/workshop"}`
	result := core.Dispatch("PreCompact", raw)

	var out map[string]any
	if err := json.Unmarshal([]byte(result), &out); err != nil {
		t.Fatalf("dispatcher output not valid JSON: %v\nraw=%s", err, result)
	}

	msg, _ := out["message"].(string)
	if msg == "" {
		t.Errorf("expected non-empty message field, got: %s", result)
	}
	if !strings.Contains(msg, "PreCompact") {
		t.Errorf("message must reference 'PreCompact', got: %q", msg)
	}
}

// TestPreCompactDataflow_CheckpointCountAfterMultipleSessions verifies that
// N distinct sessions produce exactly N checkpoint files (no phantom files).
func TestPreCompactDataflow_CheckpointCountAfterMultipleSessions(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	core.Reset()
	RegisterPreCompact()

	sessions := []string{"sa", "sb", "sc"}
	for _, sid := range sessions {
		raw := `{"session_id":"` + sid + `","trigger":"auto","cwd":"/tmp"}`
		_ = core.Dispatch("PreCompact", raw)
	}

	dir := filepath.Join(home, ".claude", "data", "pre-compact")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("ReadDir: %v", err)
	}

	jsonCount := 0
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".json") {
			jsonCount++
		}
	}
	if jsonCount != len(sessions) {
		t.Errorf("expected %d checkpoint files, found %d", len(sessions), jsonCount)
	}
}
