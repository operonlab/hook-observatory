package core

import (
	"path/filepath"
	"testing"
)

func TestDeepMerge(t *testing.T) {
	base := map[string]any{
		"handlers": map[string]any{
			"core": map[string]any{"bash_safety": true, "observability": true},
		},
		"port": 10100,
	}
	override := map[string]any{
		"handlers": map[string]any{
			"core": map[string]any{"bash_safety": false},
		},
	}
	merged := deepMerge(base, override)

	handlers := merged["handlers"].(map[string]any)
	core := handlers["core"].(map[string]any)
	if core["bash_safety"] != false {
		t.Errorf("override should win for bash_safety, got %v", core["bash_safety"])
	}
	if core["observability"] != true {
		t.Errorf("base should survive for observability, got %v", core["observability"])
	}
	if merged["port"] != 10100 {
		t.Errorf("base port should survive, got %v", merged["port"])
	}
}

func TestExpandUser(t *testing.T) {
	home, _ := filepath.Abs(expandUser("~"))
	if home == "~" {
		t.Fatal("expand(~) should resolve to home")
	}
	if got := expandUser("/absolute/path"); got != "/absolute/path" {
		t.Errorf("absolute path should not be expanded: %s", got)
	}
	if got := expandUser("relative/path"); got != "relative/path" {
		t.Errorf("relative without ~ should not be expanded: %s", got)
	}
}

func TestIsHandlerEnabledDefault(t *testing.T) {
	c := &Config{data: map[string]any{}}
	if !c.IsHandlerEnabled("unknown_handler") {
		t.Error("unknown handlers should default to enabled")
	}
}

func TestIsHandlerEnabledExplicit(t *testing.T) {
	c := &Config{data: map[string]any{
		"handlers": map[string]any{
			"core": map[string]any{"bash_safety": true, "rtk_rewrite": false},
		},
	}}
	if !c.IsHandlerEnabled("bash_safety") {
		t.Error("bash_safety should be enabled")
	}
	if c.IsHandlerEnabled("rtk_rewrite") {
		t.Error("rtk_rewrite should be disabled")
	}
}
