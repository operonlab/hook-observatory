// Package server — Config handles TOML-based configuration for Agent Vista.
package server

import (
	"fmt"
	"os"

	"github.com/BurntSushi/toml"
)

// Config holds all agent-vista configuration.
type Config struct {
	Host        string `toml:"host"`
	Port        int    `toml:"port"`
	Verbose     bool   `toml:"verbose"`
	NoBrowser   bool   `toml:"no_browser"`
	LayoutPath  string `toml:"layout_path"`
	DatabaseURL string `toml:"database_url"` // optional PostgreSQL DSN; empty = JSON file only
	RedisURL    string `toml:"redis_url"`    // optional Redis URL; empty = in-memory only

	Discovery DiscoveryConfig `toml:"discovery"`
	Monitor   MonitorConfig   `toml:"monitor"`
}

// DiscoveryConfig controls session discovery scanning behaviour.
type DiscoveryConfig struct {
	IntervalSec int  `toml:"interval_sec"`
	MaxAgeMins  int  `toml:"max_age_mins"`
	Enabled     bool `toml:"enabled"`
}

// MonitorConfig controls process resource monitoring behaviour.
type MonitorConfig struct {
	IntervalSec int  `toml:"interval_sec"`
	Enabled     bool `toml:"enabled"`
}

// DefaultConfig returns a Config with sensible defaults.
func DefaultConfig() Config {
	return Config{
		Host:       "127.0.0.1",
		Port:       8840,
		Verbose:    false,
		NoBrowser:  false,
		LayoutPath: "",
		Discovery: DiscoveryConfig{
			IntervalSec: 2,
			MaxAgeMins:  30,
			Enabled:     true,
		},
		Monitor: MonitorConfig{
			IntervalSec: 5,
			Enabled:     true,
		},
	}
}

// LoadConfig reads a TOML configuration file and merges it with defaults.
// If the file does not exist, default values are returned without error.
// Any fields absent from the TOML file retain their default values.
func LoadConfig(path string) (Config, error) {
	cfg := DefaultConfig()

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return cfg, fmt.Errorf("read config file: %w", err)
	}

	if err := toml.Unmarshal(data, &cfg); err != nil {
		return cfg, fmt.Errorf("parse config file: %w", err)
	}

	return cfg, nil
}
