package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// withHome redirects HOME + CLAUDE_SESSION_ID to a temp dir so the marker
// file lands in an isolated location.
func withHome(t *testing.T, sid string) string {
	t.Helper()
	tmp := t.TempDir()
	t.Setenv("HOME", tmp)
	t.Setenv("CLAUDE_SESSION_ID", sid)
	return tmp
}

func TestPlanImplGateExitPlanModeWritesMarker(t *testing.T) {
	home := withHome(t, "sid-exit")
	res := planImplGatePostToolUse(
		"PostToolUse", "ExitPlanMode",
		map[string]any{"plan_path": "/tmp/plan.md"},
		"",
	)
	if res.IsBlock() {
		t.Fatal("should not block")
	}
	marker := filepath.Join(home, ".hook-observatory", "markers", ".plan-approved-sid-exit")
	raw, err := os.ReadFile(marker)
	if err != nil {
		t.Fatalf("marker not written: %v", err)
	}
	var data pigMarkerData
	if err := json.Unmarshal(raw, &data); err != nil {
		t.Fatalf("marker not valid JSON: %v", err)
	}
	if data.PlanPath != "/tmp/plan.md" {
		t.Errorf("plan_path mismatch: %q", data.PlanPath)
	}
}

func TestPlanImplGateWrongToolIsNoOp(t *testing.T) {
	home := withHome(t, "sid-wrong")
	res := planImplGatePostToolUse("PostToolUse", "Edit", map[string]any{}, "")
	if res.IsBlock() {
		t.Fatal("should not block")
	}
	marker := filepath.Join(home, ".hook-observatory", "markers", ".plan-approved-sid-wrong")
	if _, err := os.Stat(marker); err == nil {
		t.Error("no marker should be written for non-ExitPlanMode tools")
	}
}

func TestPlanImplGateUserPromptInjectsReminder(t *testing.T) {
	home := withHome(t, "sid-prompt")
	// Pre-create a fresh marker
	markerDir := filepath.Join(home, ".hook-observatory", "markers")
	if err := os.MkdirAll(markerDir, 0o755); err != nil {
		t.Fatal(err)
	}
	data := pigMarkerData{
		Timestamp: float64(time.Now().Unix()),
		PlanPath:  "/tmp/plan.md",
	}
	raw, _ := json.Marshal(data)
	marker := filepath.Join(markerDir, ".plan-approved-sid-prompt")
	if err := os.WriteFile(marker, raw, 0o644); err != nil {
		t.Fatal(err)
	}

	res := planImplGateUserPrompt("UserPromptSubmit", "", map[string]any{}, "")
	if !strings.Contains(res.Text, "Plan-to-Impl Gate") {
		t.Errorf("expected reminder text, got %q", res.Text)
	}
	if _, err := os.Stat(marker); err == nil {
		t.Error("marker should be deleted after injection (one-shot)")
	}
}

func TestPlanImplGateExpiredMarkerIsDeleted(t *testing.T) {
	home := withHome(t, "sid-expired")
	markerDir := filepath.Join(home, ".hook-observatory", "markers")
	if err := os.MkdirAll(markerDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// Timestamp 2 hours ago (TTL is 1 hour)
	data := pigMarkerData{
		Timestamp: float64(time.Now().Add(-2 * time.Hour).Unix()),
		PlanPath:  "/tmp/plan.md",
	}
	raw, _ := json.Marshal(data)
	marker := filepath.Join(markerDir, ".plan-approved-sid-expired")
	_ = os.WriteFile(marker, raw, 0o644)

	res := planImplGateUserPrompt("UserPromptSubmit", "", map[string]any{}, "")
	if res.Text != "" {
		t.Errorf("expired marker should not inject, got %q", res.Text)
	}
	if _, err := os.Stat(marker); err == nil {
		t.Error("expired marker should be deleted")
	}
}

func TestPlanImplGateNoMarkerNoOp(t *testing.T) {
	withHome(t, "sid-nomark")
	res := planImplGateUserPrompt("UserPromptSubmit", "", map[string]any{}, "")
	if res.Text != "" || res.IsBlock() {
		t.Errorf("no marker should yield no-op allow, got %+v", res)
	}
}
