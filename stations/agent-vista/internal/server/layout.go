// Package server — LayoutManager handles persistent office layout storage.
package server

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"github.com/joneshong/agent-vista/internal/protocol"
)

// LayoutManager handles persistent layout storage.
// It reads/writes a JSON file at the configured path and provides
// thread-safe access to the current office layout.
type LayoutManager struct {
	path    string
	mu      sync.RWMutex
	layout  *protocol.OfficeLayout
	verbose bool
}

// NewLayoutManager creates a new LayoutManager for the given file path.
func NewLayoutManager(path string, verbose bool) *LayoutManager {
	return &LayoutManager{
		path:    path,
		verbose: verbose,
	}
}

// DefaultLayout returns the default office layout used when no file exists.
func DefaultLayout() protocol.OfficeLayout {
	return protocol.OfficeLayout{
		Version:      1,
		ActiveOffice: "main",
		Offices: []protocol.Office{{
			ID:     "main",
			Name:   "Main Office",
			Width:  50,
			Height: 34,
			Furniture: []protocol.Furniture{
				{ID: "desk-1", Type: "desk", TileX: 4, TileY: 3},
				{ID: "desk-2", Type: "desk", TileX: 9, TileY: 3},
				{ID: "desk-3", Type: "desk", TileX: 14, TileY: 3},
				{ID: "plant-1", Type: "plant", TileX: 1, TileY: 1},
			},
		}},
	}
}

// Load reads the layout from the configured file path.
// If the file does not exist, it initialises the layout with defaults
// and writes them to disk so subsequent loads find a valid file.
func (lm *LayoutManager) Load() error {
	lm.mu.Lock()
	defer lm.mu.Unlock()

	data, err := os.ReadFile(lm.path)
	if err != nil {
		if os.IsNotExist(err) {
			// First run: use defaults
			def := DefaultLayout()
			lm.layout = &def
			// Persist defaults so the file exists for future runs
			return lm.saveLocked()
		}
		return fmt.Errorf("read layout file: %w", err)
	}

	var layout protocol.OfficeLayout
	if err := json.Unmarshal(data, &layout); err != nil {
		return fmt.Errorf("parse layout file: %w", err)
	}
	lm.layout = &layout
	return nil
}

// Save writes the current layout to disk atomically.
func (lm *LayoutManager) Save() error {
	lm.mu.RLock()
	defer lm.mu.RUnlock()

	if lm.layout == nil {
		return fmt.Errorf("no layout loaded")
	}
	return lm.saveLocked()
}

// Get returns a copy of the current layout.
func (lm *LayoutManager) Get() protocol.OfficeLayout {
	lm.mu.RLock()
	defer lm.mu.RUnlock()

	if lm.layout == nil {
		return DefaultLayout()
	}
	return *lm.layout
}

// Update replaces the current layout and persists it to disk.
func (lm *LayoutManager) Update(layout protocol.OfficeLayout) error {
	lm.mu.Lock()
	defer lm.mu.Unlock()

	lm.layout = &layout
	return lm.saveLocked()
}

// saveLocked writes the layout to disk via a temp file + rename for atomicity.
// Caller must hold at least a read lock on lm.mu.
func (lm *LayoutManager) saveLocked() error {
	dir := filepath.Dir(lm.path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create layout directory: %w", err)
	}

	data, err := json.MarshalIndent(lm.layout, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal layout: %w", err)
	}
	data = append(data, '\n')

	tmpPath := lm.path + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0o644); err != nil {
		return fmt.Errorf("write temp layout file: %w", err)
	}
	if err := os.Rename(tmpPath, lm.path); err != nil {
		os.Remove(tmpPath) // best-effort cleanup
		return fmt.Errorf("rename temp layout file: %w", err)
	}
	return nil
}
