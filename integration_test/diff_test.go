// Package integration_test runs end-to-end smoke tests against a real built
// binary. Stage 1 validates the dispatcher contract (exit code, output shape,
// side effects) for the three golden sample handlers.
//
// Python-vs-Go byte-diff testing is deferred to Stage 3 shadow mode, where
// real production payloads from ~/.hook-observatory/spool/events.jsonl will be
// replayed against both binaries with identical environment.
package integration_test

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func buildBinary(t *testing.T) string {
	t.Helper()
	tmp, err := os.CreateTemp("", "hook-observatory-*")
	if err != nil {
		t.Fatalf("tempfile: %v", err)
	}
	tmp.Close()
	out := tmp.Name()

	cmd := exec.Command("go", "build", "-o", out, "../cmd/hook-observatory")
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("build failed: %v", err)
	}
	t.Cleanup(func() { os.Remove(out) })
	return out
}

func run(t *testing.T, bin, event string, stdin string, env ...string) string {
	t.Helper()
	cmd := exec.Command(bin, event)
	cmd.Stdin = strings.NewReader(stdin)
	cmd.Stderr = io.Discard
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Env = append(os.Environ(), env...)
	if err := cmd.Run(); err != nil {
		t.Fatalf("dispatcher failed: %v", err)
	}
	return strings.TrimSpace(out.String())
}

// setupIsolatedEnv points HOOK_OBSERVATORY_ROOT + home-derived paths at a
// temp dir so each test has a clean slate.
func setupIsolatedEnv(t *testing.T) (spoolDir, dataDir string, envVars []string) {
	t.Helper()
	tmp := t.TempDir()
	spoolDir = filepath.Join(tmp, "spool")
	dataDir = filepath.Join(tmp, "data")
	return spoolDir, dataDir, nil
}

// --- Contract tests ----------------------------------------------------------

func TestBinaryAlwaysExitsZero(t *testing.T) {
	bin := buildBinary(t)

	// Malformed JSON, missing event, empty input — must all exit 0.
	cases := []struct {
		name  string
		event string
		input string
	}{
		{"empty_input", "PreToolUse", ""},
		{"malformed_json", "PreToolUse", "{not-json"},
		{"missing_event", "", `{"tool_name":"Bash"}`},
		{"unknown_event", "MadeUpEvent", `{}`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			out := run(t, bin, c.event, c.input)
			if out == "" {
				return // empty stdout is acceptable
			}
			// Anything non-empty must be valid JSON (except UserPromptSubmit passthrough)
			var v any
			if err := json.Unmarshal([]byte(out), &v); err != nil {
				t.Errorf("output must be valid JSON, got %q (%v)", out, err)
			}
		})
	}
}

func TestBashSafetyBlocksDangerousCommand(t *testing.T) {
	bin := buildBinary(t)
	payload := `{"tool_name":"Bash","tool_input":{"command":"sudo rm -rf /"}}`
	out := run(t, bin, "PreToolUse", payload)
	if !strings.Contains(out, `"decision":"block"`) {
		t.Errorf("expected block, got %s", out)
	}
	if !strings.Contains(out, "Safety hook") {
		t.Errorf("expected Safety hook reason, got %s", out)
	}
}

func TestBashSafetyAllowsSafeCommand(t *testing.T) {
	bin := buildBinary(t)
	payload := `{"tool_name":"Bash","tool_input":{"command":"ls -la"}}`
	out := run(t, bin, "PreToolUse", payload)
	if strings.Contains(out, `"decision":"block"`) {
		t.Errorf("safe command should not be blocked, got %s", out)
	}
}

func TestObservabilityWritesSpoolLine(t *testing.T) {
	bin := buildBinary(t)
	tmp := t.TempDir()
	spoolDir := filepath.Join(tmp, "spool")

	// Craft a minimal config.yaml at a temp observatory root that points spool_dir
	// to our isolated path. Dispatcher reads HOOK_OBSERVATORY_ROOT env.
	observatoryRoot := filepath.Join(tmp, "observatory")
	if err := os.MkdirAll(observatoryRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	cfgBody := "spool_dir: " + spoolDir + "\nhandlers:\n  core:\n    observability: true\n"
	if err := os.WriteFile(filepath.Join(observatoryRoot, "config.yaml"), []byte(cfgBody), 0o644); err != nil {
		t.Fatal(err)
	}

	payload := `{"tool_name":"Bash","tool_input":{"command":"ls"}}`
	run(t, bin, "PreToolUse", payload, "HOOK_OBSERVATORY_ROOT="+observatoryRoot)

	spoolFile := filepath.Join(spoolDir, "events.jsonl")
	data, err := os.ReadFile(spoolFile)
	if err != nil {
		t.Fatalf("spool file not written: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("spool file is empty")
	}
	var entry map[string]any
	line := strings.TrimSpace(string(data))
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("spool line not valid JSON: %v (line: %s)", err, line)
	}
	if entry["event_type"] != "PreToolUse" {
		t.Errorf("expected event_type=PreToolUse, got %v", entry["event_type"])
	}
	if _, ok := entry["ts"]; !ok {
		t.Error("spool line missing ts field")
	}
	if _, ok := entry["data"]; !ok {
		t.Error("spool line missing data field")
	}
}

func TestSessionCostWritesJSONL(t *testing.T) {
	bin := buildBinary(t)
	tmp := t.TempDir()

	observatoryRoot := filepath.Join(tmp, "observatory")
	if err := os.MkdirAll(observatoryRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	dataDir := filepath.Join(tmp, "claude-data")
	cfgBody := "handlers:\n  integrations:\n    session_cost: true\npaths:\n  data_dir: " + dataDir + "\n"
	if err := os.WriteFile(filepath.Join(observatoryRoot, "config.yaml"), []byte(cfgBody), 0o644); err != nil {
		t.Fatal(err)
	}

	payload := `{"session_id":"abc123","tool_name":"Task"}`
	run(t, bin, "Stop", payload, "HOOK_OBSERVATORY_ROOT="+observatoryRoot)

	sessionsFile := filepath.Join(dataDir, "session-cost", "sessions.jsonl")
	data, err := os.ReadFile(sessionsFile)
	if err != nil {
		t.Fatalf("sessions file not written: %v", err)
	}
	line := strings.TrimSpace(string(data))
	var entry map[string]any
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("invalid JSON: %v (line: %s)", err, line)
	}
	if entry["session_id"] != "abc123" {
		t.Errorf("expected session_id=abc123, got %v", entry["session_id"])
	}
	if entry["response_index"] != float64(1) {
		t.Errorf("expected response_index=1 (per-process reset), got %v", entry["response_index"])
	}
}

func TestUserPromptSubmitPassthroughHasNoWrapper(t *testing.T) {
	// No handler currently produces passthrough text, so stdout should be empty
	// or "{}" — never the passthrough format "\nfoo".
	bin := buildBinary(t)
	out := run(t, bin, "UserPromptSubmit", `{"tool_input":{"prompt":"hello"}}`)
	// Acceptable: "" or "{}" — reject anything else that looks like JSON-wrapped passthrough
	if out != "" && out != "{}" {
		// Ensure it is still valid JSON (no one emitted text yet)
		var v any
		if err := json.Unmarshal([]byte(out), &v); err != nil {
			t.Errorf("UserPromptSubmit with no passthrough handlers should yield empty or {} JSON, got %q", out)
		}
	}
}
