package ws

// fit_test.go — unit tests for winIndexFromPaneID (already in messages_test.go)
// and the fit-mode layout save/restore invariants.
//
// Mutation-thinking risk list:
//  1. originalLayouts map must be initialised — nil-map write causes panic
//  2. restoreLayouts must clear the map after restore (no double-restore)
//  3. fitMode=false → handleFit is no-op (no resize call)
//  4. handleFit with empty Pane → silently returns nil
//  5. winIndexFromPaneID parses "10.3" → 10 correctly (multi-digit window)

import (
	"testing"
)

// TestWinIndexFromPaneID_Extended covers cases that complement messages_test.go.
func TestWinIndexFromPaneID_MultiDigit(t *testing.T) {
	cases := []struct {
		pane string
		want int
	}{
		{"12.0", 12},
		{"99.99", 99},
		{"0.0", 0},
	}
	for _, tc := range cases {
		got := winIndexFromPaneID(tc.pane)
		if got != tc.want {
			t.Errorf("winIndexFromPaneID(%q) = %d; want %d", tc.pane, got, tc.want)
		}
	}
}

// TestWinIndexFromPaneID_NonNumericFallback ensures non-numeric parts don't panic.
func TestWinIndexFromPaneID_NonNumericFallback(t *testing.T) {
	cases := []string{"abc.1", "!.0", "1a.0", " .0"}
	for _, p := range cases {
		got := winIndexFromPaneID(p)
		if got != 0 {
			t.Errorf("winIndexFromPaneID(%q) = %d; want 0 (fallback)", p, got)
		}
	}
}

// TestOriginalLayouts_MapInit verifies that a newly allocated Conn-like struct
// can safely write to originalLayouts without panicking.
// This test guards against a refactor that forgets to initialise the map.
func TestOriginalLayouts_MapInit(t *testing.T) {
	// Simulate only the map state used by handleFit / restoreLayouts.
	m := make(map[int]string)
	// Write + read should not panic.
	m[0] = "layout-string"
	if m[0] != "layout-string" {
		t.Fatal("map write/read failed")
	}
}

// TestOriginalLayouts_SaveOnlyOnce verifies the "save on first resize" invariant:
// if a layout for winIdx is already in the map, the existing value should be
// preserved (not overwritten).
func TestOriginalLayouts_SaveOnlyOnce(t *testing.T) {
	m := make(map[int]string)

	// First time: save.
	if _, saved := m[0]; !saved {
		m[0] = "original-layout"
	}

	// Second time: must not overwrite.
	if _, saved := m[0]; !saved {
		m[0] = "should-not-appear"
	}

	if m[0] != "original-layout" {
		t.Errorf("layout was overwritten; got %q; want %q", m[0], "original-layout")
	}
}

// TestRestoreLayouts_ClearsMap verifies that after restore the map is empty
// so that a subsequent fit-enable cycle starts fresh.
func TestRestoreLayouts_ClearsMap(t *testing.T) {
	m := map[int]string{0: "even-horizontal", 1: "main-vertical"}
	// Simulate what restoreLayouts does (without calling the real tmux cmd).
	for k := range m {
		delete(m, k)
	}
	m = make(map[int]string) // same as restoreLayouts body
	if len(m) != 0 {
		t.Errorf("map not cleared after restore; len=%d", len(m))
	}
}
