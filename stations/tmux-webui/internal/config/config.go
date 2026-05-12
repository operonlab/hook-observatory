// Package config loads tmux-webui configuration from disk.
//
// v0 uses JSON (stdlib only, no external deps). Layered config (env →
// flags → file with override semantics) is deferred to v0.2 when there
// is concrete demand; KISS for now.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

type Config struct {
	Host            string             `json:"host"`
	Port            int                `json:"port"`
	PollInterval    float64            `json:"poll_interval"`
	MetricsInterval float64            `json:"metrics_interval"`
	CaptureLines    int                `json:"capture_lines"`
	UploadDir       string             `json:"upload_dir"`
	Autocomplete    AutocompleteConfig `json:"autocomplete"`
	Metrics         MetricsConfig      `json:"metrics"`
	Relay           RelayConfig        `json:"relay,omitempty"`
}

type AutocompleteConfig struct {
	// ClaudeDir, when set, enables scanning ~/.claude/{skills,commands,agents}.
	// Empty disables Claude resource autocomplete; path autocomplete is always on.
	ClaudeDir string `json:"claude_dir,omitempty"`
}

type MetricsConfig struct {
	// Provider: "gopsutil" (default, built-in) or "http" (pull from URL).
	Provider string `json:"provider"`
	// URL is consumed when Provider == "http". Workshop dogfood points this
	// at http://127.0.0.1:10103/sysmon/current.
	URL string `json:"url,omitempty"`
}

type RelayConfig struct {
	// PaneScript is the path to a shell script that allocates a relay pane.
	// Empty disables /api/relay (returns 501).
	PaneScript  string `json:"pane_pool_script,omitempty"`
	RelayScript string `json:"relay_script,omitempty"`
	SignalDir   string `json:"signal_dir,omitempty"`
}

func Defaults() Config {
	cache, _ := os.UserCacheDir()
	return Config{
		Host:            "127.0.0.1",
		Port:            9527,
		PollInterval:    0.4,
		MetricsInterval: 5.0,
		CaptureLines:    150,
		UploadDir:       filepath.Join(cache, "tmux-webui", "uploads"),
		Metrics:         MetricsConfig{Provider: "gopsutil"},
	}
}

func DefaultPath() string {
	if p := os.Getenv("TMUX_WEBUI_CONFIG"); p != "" {
		return p
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".config", "tmux-webui", "config.json")
}

// Load reads config from path (or DefaultPath if empty).
// On first run (file missing), it auto-creates the file with defaults so
// non-technical users get a working config they can edit.
func Load(path string) (*Config, error) {
	if path == "" {
		path = DefaultPath()
	}
	cfg := Defaults()

	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		if werr := writeDefaults(path, cfg); werr != nil {
			fmt.Fprintln(os.Stderr, "tmux-webui: could not create default config:", werr)
		}
		return &cfg, nil
	}
	if err != nil {
		return nil, fmt.Errorf("config read %s: %w", path, err)
	}
	if len(data) == 0 {
		return &cfg, nil
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("config parse %s: %w", path, err)
	}
	return &cfg, nil
}

func writeDefaults(path string, cfg Config) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0o644)
}
