package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaults(t *testing.T) {
	d := Defaults()
	if d.Host != "127.0.0.1" {
		t.Errorf("Host=%q; want 127.0.0.1", d.Host)
	}
	if d.Port != 9527 {
		t.Errorf("Port=%d; want 9527", d.Port)
	}
	if d.PollInterval != 0.4 {
		t.Errorf("PollInterval=%v; want 0.4", d.PollInterval)
	}
	if d.CaptureLines != 150 {
		t.Errorf("CaptureLines=%d; want 150", d.CaptureLines)
	}
	if d.Metrics.Provider != "gopsutil" {
		t.Errorf("Metrics.Provider=%q; want gopsutil", d.Metrics.Provider)
	}
}

func TestLoadAutoCreate(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Port != 9527 {
		t.Errorf("expected default port 9527 on auto-create, got %d", cfg.Port)
	}
	// File should exist now.
	if _, err := os.Stat(path); err != nil {
		t.Errorf("expected config file auto-created at %s, got %v", path, err)
	}
}

func TestLoadOverrides(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	body := `{"host":"0.0.0.0","port":12345,"capture_lines":300,"metrics":{"provider":"http","url":"http://localhost:10103/sysmon/current"}}`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Host != "0.0.0.0" {
		t.Errorf("Host=%q; want 0.0.0.0", cfg.Host)
	}
	if cfg.Port != 12345 {
		t.Errorf("Port=%d; want 12345", cfg.Port)
	}
	if cfg.CaptureLines != 300 {
		t.Errorf("CaptureLines=%d; want 300", cfg.CaptureLines)
	}
	if cfg.Metrics.URL != "http://localhost:10103/sysmon/current" {
		t.Errorf("Metrics.URL=%q", cfg.Metrics.URL)
	}
	// Defaults preserved for unspecified fields.
	if cfg.PollInterval != 0.4 {
		t.Errorf("PollInterval=%v; want default 0.4", cfg.PollInterval)
	}
}
