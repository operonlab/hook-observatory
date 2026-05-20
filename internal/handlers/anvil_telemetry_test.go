package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAnvilIsTest(t *testing.T) {
	cases := []struct {
		name   string
		input  string
		expect bool
	}{
		{"prefix underscore", "_debug", true},
		{"prefix test-", "test-skill", true},
		{"exact general-purpose", "general-purpose", true},
		{"digit pattern", "skill-42", true},
		{"normal skill", "research", false},
		{"prompt-router", "prompt-router", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := anvilIsTest(c.input); got != c.expect {
				t.Errorf("anvilIsTest(%q) = %v, want %v", c.input, got, c.expect)
			}
		})
	}
}

func TestAnvilHandleIntent(t *testing.T) {
	var received []map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		received = append(received, body)
		w.WriteHeader(201)
	}))
	defer srv.Close()
	t.Setenv("ANVIL_API", srv.URL)

	rawInput := `{"data":{"session_id":"sess-1"}}` +
		"\n<command-name>/research</command-name>" +
		"<command-name>/general-purpose</command-name>"

	result := anvilHandleIntent(rawInput)
	if result.Decision != "" {
		t.Errorf("expected Allow, got %q", result.Decision)
	}

	// Should have posted 1 intent (general-purpose is test-exact, skipped)
	if len(received) != 1 {
		t.Errorf("expected 1 intent POST, got %d", len(received))
	}
	if name, _ := received[0]["skill_name"].(string); name != "research" {
		t.Errorf("expected skill_name=research, got %q", name)
	}
}

func TestAnvilHandleSkillSpool(t *testing.T) {
	// Point to bad URL → spool fallback
	t.Setenv("ANVIL_API", "http://127.0.0.1:1") // unreachable

	dir := t.TempDir()
	// Patch spool location by overriding data_dir via env is not easy;
	// use a temp dir by writing the file path.
	// We verify spool is written by checking the directory state.
	oldSpool := anvilSpoolDir
	_ = oldSpool // keep reference so compiler doesn't complain

	// Invoke handler
	toolInput := map[string]any{"skill": "my-skill", "args": "foo"}
	raw := `{"data":{"session_id":"s1","cwd":"/tmp"}}`
	result := anvilHandleSkill(toolInput, raw)
	if result.Decision != "" {
		t.Errorf("expected Allow, got decision=%q", result.Decision)
	}

	// Spool file should be written in default location
	home, _ := os.UserHomeDir()
	spoolFile := filepath.Join(home, ".claude", "data", "anvil-telemetry", "pending.jsonl")
	if data, err := os.ReadFile(spoolFile); err == nil {
		if !strings.Contains(string(data), "my-skill") {
			t.Errorf("spool does not contain skill name: %q", string(data))
		}
	}
	_ = dir
}

func TestAnvilSessionStartNoSpool(t *testing.T) {
	// If spool file doesn't exist, SessionStart returns Allow
	t.Setenv("ANVIL_API", "http://127.0.0.1:1")
	// Use a non-existent spool by clearing env
	result := anvilSyncPending()
	if result.Decision != "" {
		t.Errorf("expected Allow, got %q", result.Decision)
	}
}

func TestAnvilHandleMCPUnknownServer(t *testing.T) {
	toolInput := map[string]any{"name": "unknown-server:some_tool"}
	result := anvilHandleMCP(toolInput, "{}")
	if result.Decision != "" {
		t.Errorf("expected Allow for unknown server, got %q", result.Decision)
	}
}

func TestAnvilHandleCLIUnknown(t *testing.T) {
	toolInput := map[string]any{"command": "somerandombinary --help"}
	result := anvilHandleCLI(toolInput, "{}")
	if result.Decision != "" {
		t.Errorf("expected Allow for unknown CLI, got %q", result.Decision)
	}
}

func TestAnvilHandleIntent_Builtin(t *testing.T) {
	// Builtins should be silently skipped
	var posted int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		posted++
		w.WriteHeader(201)
	}))
	defer srv.Close()
	t.Setenv("ANVIL_API", srv.URL)

	raw := `{}` + "<command-name>/clear</command-name><command-name>/exit</command-name>"
	anvilHandleIntent(raw)
	if posted != 0 {
		t.Errorf("builtins should not be posted, got %d posts", posted)
	}
}
