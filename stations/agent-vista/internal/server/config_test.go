package server

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaultConfig(t *testing.T) {
	cfg := DefaultConfig()

	if cfg.Port != 8840 {
		t.Errorf("expected port 8840, got %d", cfg.Port)
	}
	if cfg.Verbose {
		t.Error("expected verbose=false")
	}
	if cfg.NoBrowser {
		t.Error("expected no_browser=false")
	}
	if cfg.LayoutPath != "" {
		t.Errorf("expected empty layout_path, got %q", cfg.LayoutPath)
	}

	// Discovery defaults
	if cfg.Discovery.IntervalSec != 2 {
		t.Errorf("expected discovery interval_sec=2, got %d", cfg.Discovery.IntervalSec)
	}
	if cfg.Discovery.MaxAgeMins != 30 {
		t.Errorf("expected discovery max_age_mins=30, got %d", cfg.Discovery.MaxAgeMins)
	}
	if !cfg.Discovery.Enabled {
		t.Error("expected discovery enabled=true")
	}

	// Monitor defaults
	if cfg.Monitor.IntervalSec != 5 {
		t.Errorf("expected monitor interval_sec=5, got %d", cfg.Monitor.IntervalSec)
	}
	if !cfg.Monitor.Enabled {
		t.Error("expected monitor enabled=true")
	}
}

func TestLoadConfigFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.toml")

	content := `
port = 9090
verbose = true
no_browser = true
layout_path = "/custom/layout.json"

[discovery]
interval_sec = 5
max_age_mins = 60
enabled = false

[monitor]
interval_sec = 10
enabled = false
`
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile(): %v", err)
	}

	cfg, err := LoadConfig(path)
	if err != nil {
		t.Fatalf("LoadConfig(): %v", err)
	}

	if cfg.Port != 9090 {
		t.Errorf("expected port 9090, got %d", cfg.Port)
	}
	if !cfg.Verbose {
		t.Error("expected verbose=true")
	}
	if !cfg.NoBrowser {
		t.Error("expected no_browser=true")
	}
	if cfg.LayoutPath != "/custom/layout.json" {
		t.Errorf("expected layout_path '/custom/layout.json', got %q", cfg.LayoutPath)
	}

	if cfg.Discovery.IntervalSec != 5 {
		t.Errorf("expected discovery interval_sec=5, got %d", cfg.Discovery.IntervalSec)
	}
	if cfg.Discovery.MaxAgeMins != 60 {
		t.Errorf("expected discovery max_age_mins=60, got %d", cfg.Discovery.MaxAgeMins)
	}
	if cfg.Discovery.Enabled {
		t.Error("expected discovery enabled=false")
	}

	if cfg.Monitor.IntervalSec != 10 {
		t.Errorf("expected monitor interval_sec=10, got %d", cfg.Monitor.IntervalSec)
	}
	if cfg.Monitor.Enabled {
		t.Error("expected monitor enabled=false")
	}
}

func TestLoadConfigMissing(t *testing.T) {
	cfg, err := LoadConfig("/non/existent/config.toml")
	if err != nil {
		t.Fatalf("LoadConfig() on missing file should not error, got: %v", err)
	}

	// Should return defaults
	def := DefaultConfig()
	if cfg.Port != def.Port {
		t.Errorf("expected default port %d, got %d", def.Port, cfg.Port)
	}
	if cfg.Discovery.IntervalSec != def.Discovery.IntervalSec {
		t.Errorf("expected default discovery interval %d, got %d", def.Discovery.IntervalSec, cfg.Discovery.IntervalSec)
	}
	if cfg.Monitor.Enabled != def.Monitor.Enabled {
		t.Errorf("expected default monitor enabled=%v, got %v", def.Monitor.Enabled, cfg.Monitor.Enabled)
	}
}

func TestPartialConfig(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.toml")

	// Only set port and discovery interval; everything else should use defaults
	content := `
port = 7777

[discovery]
interval_sec = 10
`
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile(): %v", err)
	}

	cfg, err := LoadConfig(path)
	if err != nil {
		t.Fatalf("LoadConfig(): %v", err)
	}

	// Overridden values
	if cfg.Port != 7777 {
		t.Errorf("expected port 7777, got %d", cfg.Port)
	}
	if cfg.Discovery.IntervalSec != 10 {
		t.Errorf("expected discovery interval_sec=10, got %d", cfg.Discovery.IntervalSec)
	}

	// Values that should remain at defaults
	if cfg.Verbose {
		t.Error("expected verbose=false (default)")
	}
	if cfg.NoBrowser {
		t.Error("expected no_browser=false (default)")
	}
	if cfg.Discovery.MaxAgeMins != 30 {
		t.Errorf("expected discovery max_age_mins=30 (default), got %d", cfg.Discovery.MaxAgeMins)
	}
	if !cfg.Discovery.Enabled {
		t.Error("expected discovery enabled=true (default)")
	}
	if cfg.Monitor.IntervalSec != 5 {
		t.Errorf("expected monitor interval_sec=5 (default), got %d", cfg.Monitor.IntervalSec)
	}
	if !cfg.Monitor.Enabled {
		t.Error("expected monitor enabled=true (default)")
	}
}
