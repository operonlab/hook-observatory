package core

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

// Config mirrors handlers/hook_config.py cfg.
//
// Load order: config.example.yaml (defaults) → config.yaml (user overrides).
// Paths are expanded (~ → $HOME). observatory_root: "auto" is resolved to the
// actual observatory directory.
type Config struct {
	data map[string]any
	root string
}

var (
	cfgOnce     sync.Once
	cfgInstance *Config
)

// Cfg returns the process-wide config singleton.
func Cfg() *Config {
	cfgOnce.Do(func() {
		cfgInstance = loadConfig()
	})
	return cfgInstance
}

// observatoryRoot resolves the hook-dispatcher source directory (legacy name
// kept for internal callers — the directory was renamed from hook-observatory
// when Python was retired in 2026-05). Priority:
//
//	HOOK_DISPATCHER_ROOT env → HOOK_OBSERVATORY_ROOT env (backward-compat) →
//	~/workshop/stations/hook-dispatcher.
func observatoryRoot() string {
	if v := os.Getenv("HOOK_DISPATCHER_ROOT"); v != "" {
		return expandUser(v)
	}
	if v := os.Getenv("HOOK_OBSERVATORY_ROOT"); v != "" {
		return expandUser(v)
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "workshop", "stations", "hook-dispatcher")
}

func loadConfig() *Config {
	root := observatoryRoot()
	c := &Config{data: map[string]any{}, root: root}

	if defaults := readYAML(filepath.Join(root, "config.example.yaml")); defaults != nil {
		c.data = defaults
	}
	if overrides := readYAML(filepath.Join(root, "config.yaml")); overrides != nil {
		c.data = deepMerge(c.data, overrides)
	}

	// Expand ~ in paths map
	if paths, ok := c.data["paths"].(map[string]any); ok {
		for k, v := range paths {
			if s, ok := v.(string); ok && s != "auto" {
				paths[k] = expandUser(s)
			}
		}
		if v, _ := paths["observatory_root"].(string); v == "auto" || v == "" {
			paths["observatory_root"] = root
		}
	}
	return c
}

func readYAML(path string) map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var out map[string]any
	if err := yaml.Unmarshal(data, &out); err != nil {
		return nil
	}
	return out
}

func deepMerge(base, override map[string]any) map[string]any {
	out := make(map[string]any, len(base))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range override {
		if existing, ok := out[k].(map[string]any); ok {
			if newMap, ok := v.(map[string]any); ok {
				out[k] = deepMerge(existing, newMap)
				continue
			}
		}
		out[k] = v
	}
	return out
}

func expandUser(p string) string {
	if !strings.HasPrefix(p, "~") {
		return p
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	if p == "~" {
		return home
	}
	if strings.HasPrefix(p, "~/") {
		return filepath.Join(home, p[2:])
	}
	return p
}

// IsHandlerEnabled mirrors hook_config.is_handler_enabled.
// Defaults to true when the handler name is not found (backward compat).
func (c *Config) IsHandlerEnabled(name string) bool {
	handlers, _ := c.data["handlers"].(map[string]any)
	for _, v := range handlers {
		if category, ok := v.(map[string]any); ok {
			if val, found := category[name]; found {
				if b, ok := val.(bool); ok {
					return b
				}
			}
		}
	}
	return true
}

// GetTool resolves a tool path. "auto" → exec.LookPath; explicit → return if file exists.
func (c *Config) GetTool(name string) string {
	tools, _ := c.data["tools"].(map[string]any)
	val, ok := tools[name].(string)
	if !ok || val == "auto" {
		p, _ := exec.LookPath(name)
		return p
	}
	expanded := expandUser(val)
	if info, err := os.Stat(expanded); err == nil && !info.IsDir() {
		return expanded
	}
	return ""
}

// GetService returns a service URL by name.
func (c *Config) GetService(name string) string {
	services, _ := c.data["services"].(map[string]any)
	v, _ := services[name].(string)
	return v
}

// GetPath returns a named path (expanded), empty if unset.
func (c *Config) GetPath(name string) string {
	paths, _ := c.data["paths"].(map[string]any)
	v, _ := paths[name].(string)
	if v == "" {
		return ""
	}
	return expandUser(v)
}

// GetSpoolDir returns the spool directory (for observability).
func (c *Config) GetSpoolDir() string {
	if v, ok := c.data["spool_dir"].(string); ok && v != "" {
		return expandUser(v)
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".hook-observatory", "spool")
}

// GetTimeout returns the hook timeout in seconds for an event type.
func (c *Config) GetTimeout(eventType string) int {
	if dispatcher, ok := c.data["dispatcher"].(map[string]any); ok {
		if timeouts, ok := dispatcher["hook_timeouts"].(map[string]any); ok {
			if v, ok := timeouts[eventType].(int); ok {
				return v
			}
		}
	}
	return 20
}

// GetBudgetMs returns the deferrable handler budget in milliseconds.
func (c *Config) GetBudgetMs() int {
	if dispatcher, ok := c.data["dispatcher"].(map[string]any); ok {
		if v, ok := dispatcher["blocking_budget_ms"].(int); ok {
			return v
		}
	}
	return 5000
}
