package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/joneshong/agent-vista/internal/protocol"
)

func TestLoadDefault(t *testing.T) {
	// Load from a path that does not exist -> should create defaults
	dir := t.TempDir()
	path := filepath.Join(dir, "subdir", "layout.json")

	lm := NewLayoutManager(path, false)
	if err := lm.Load(); err != nil {
		t.Fatalf("Load() from non-existent file: %v", err)
	}

	layout := lm.Get()
	if layout.Version != 1 {
		t.Errorf("expected version 1, got %d", layout.Version)
	}
	if layout.ActiveOffice != "main" {
		t.Errorf("expected active_office 'main', got %q", layout.ActiveOffice)
	}
	if len(layout.Offices) != 1 {
		t.Fatalf("expected 1 office, got %d", len(layout.Offices))
	}

	office := layout.Offices[0]
	if office.ID != "main" {
		t.Errorf("expected office ID 'main', got %q", office.ID)
	}
	if office.Name != "Main Office" {
		t.Errorf("expected office name 'Main Office', got %q", office.Name)
	}
	if office.Width != 50 || office.Height != 34 {
		t.Errorf("expected 50x34 office, got %dx%d", office.Width, office.Height)
	}
	if len(office.Furniture) < 4 {
		t.Errorf("expected at least 4 furniture items, got %d", len(office.Furniture))
	}

	// Verify the file was written to disk
	if _, err := os.Stat(path); os.IsNotExist(err) {
		t.Error("expected layout file to be created on disk after Load()")
	}
}

func TestSaveAndLoad(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "layout.json")

	// Create a custom layout, save it
	custom := protocol.OfficeLayout{
		Version:      2,
		ActiveOffice: "test-office",
		Offices: []protocol.Office{{
			ID:     "test-office",
			Name:   "Test Office",
			Width:  30,
			Height: 20,
			Furniture: []protocol.Furniture{
				{ID: "desk-A", Type: "desk", TileX: 5, TileY: 5},
			},
		}},
	}

	lm1 := NewLayoutManager(path, false)
	// Need to load first (initialises internal state)
	if err := lm1.Load(); err != nil {
		t.Fatalf("initial Load(): %v", err)
	}
	if err := lm1.Update(custom); err != nil {
		t.Fatalf("Update(): %v", err)
	}

	// Load with a fresh LayoutManager to verify roundtrip
	lm2 := NewLayoutManager(path, false)
	if err := lm2.Load(); err != nil {
		t.Fatalf("Load() after save: %v", err)
	}

	loaded := lm2.Get()
	if loaded.Version != 2 {
		t.Errorf("expected version 2, got %d", loaded.Version)
	}
	if loaded.ActiveOffice != "test-office" {
		t.Errorf("expected active_office 'test-office', got %q", loaded.ActiveOffice)
	}
	if len(loaded.Offices) != 1 {
		t.Fatalf("expected 1 office, got %d", len(loaded.Offices))
	}
	if loaded.Offices[0].Width != 30 {
		t.Errorf("expected width 30, got %d", loaded.Offices[0].Width)
	}
	if len(loaded.Offices[0].Furniture) != 1 {
		t.Errorf("expected 1 furniture item, got %d", len(loaded.Offices[0].Furniture))
	}
	if loaded.Offices[0].Furniture[0].ID != "desk-A" {
		t.Errorf("expected furniture ID 'desk-A', got %q", loaded.Offices[0].Furniture[0].ID)
	}
}

func TestUpdateAndGet(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "layout.json")

	lm := NewLayoutManager(path, false)
	if err := lm.Load(); err != nil {
		t.Fatalf("Load(): %v", err)
	}

	// Verify default
	orig := lm.Get()
	if orig.Version != 1 {
		t.Fatalf("expected default version 1, got %d", orig.Version)
	}

	// Update with new layout
	updated := protocol.OfficeLayout{
		Version:      3,
		ActiveOffice: "new-office",
		Offices: []protocol.Office{{
			ID:     "new-office",
			Name:   "New Office",
			Width:  10,
			Height: 10,
		}},
	}
	if err := lm.Update(updated); err != nil {
		t.Fatalf("Update(): %v", err)
	}

	got := lm.Get()
	if got.Version != 3 {
		t.Errorf("expected version 3 after update, got %d", got.Version)
	}
	if got.ActiveOffice != "new-office" {
		t.Errorf("expected active_office 'new-office', got %q", got.ActiveOffice)
	}
	if len(got.Offices) != 1 || got.Offices[0].Name != "New Office" {
		t.Errorf("unexpected office after update: %+v", got.Offices)
	}

	// Verify Get returns a copy (mutating it does not affect internal state)
	got.Version = 999
	check := lm.Get()
	if check.Version == 999 {
		t.Error("Get() returned a reference instead of a copy")
	}
}

func TestAtomicWrite(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "layout.json")

	lm := NewLayoutManager(path, false)
	if err := lm.Load(); err != nil {
		t.Fatalf("Load(): %v", err)
	}

	// Update to trigger a save
	layout := DefaultLayout()
	layout.Version = 42
	if err := lm.Update(layout); err != nil {
		t.Fatalf("Update(): %v", err)
	}

	// Read the raw file and verify it's valid JSON
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile(): %v", err)
	}

	var parsed protocol.OfficeLayout
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("file content is not valid JSON: %v", err)
	}
	if parsed.Version != 42 {
		t.Errorf("expected version 42 in file, got %d", parsed.Version)
	}

	// Verify no .tmp file was left behind
	tmpPath := path + ".tmp"
	if _, err := os.Stat(tmpPath); !os.IsNotExist(err) {
		t.Errorf("expected .tmp file to be cleaned up, but it exists")
	}
}
