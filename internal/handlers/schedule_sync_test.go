package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestScheduleSyncEncodePlistInterval(t *testing.T) {
	dict := map[string]any{
		"Label":             "com.joneshong.scheduler.demo",
		"ProgramArguments":  []string{"/bin/zsh", "-lc", "echo hi"},
		"StandardOutPath":   "/tmp/demo.log",
		"StandardErrorPath": "/tmp/demo.err",
		"StartInterval":     300,
	}
	out := scheduleSyncEncodePlist(dict)

	// Header preserved
	if !strings.HasPrefix(out, `<?xml version="1.0" encoding="UTF-8"?>`) {
		t.Fatalf("missing xml header")
	}
	if !strings.Contains(out, `<plist version="1.0">`) {
		t.Fatalf("missing plist tag")
	}
	// Keys alphabetically sorted → Label < ProgramArguments < StandardErrorPath <
	// StandardOutPath < StartInterval.
	idxLabel := strings.Index(out, "<key>Label</key>")
	idxStartInterval := strings.Index(out, "<key>StartInterval</key>")
	if idxLabel < 0 || idxStartInterval < 0 || idxLabel > idxStartInterval {
		t.Fatalf("expected alphabetical key order; got:\n%s", out)
	}
	if !strings.Contains(out, "<integer>300</integer>") {
		t.Fatalf("expected StartInterval=300 integer encoding")
	}
	// Array preserved in declaration order
	if !strings.Contains(out, "<string>/bin/zsh</string>") ||
		!strings.Contains(out, "<string>-lc</string>") ||
		!strings.Contains(out, "<string>echo hi</string>") {
		t.Fatalf("ProgramArguments mis-encoded:\n%s", out)
	}
}

func TestScheduleSyncEncodePlistCalendarKeepAlive(t *testing.T) {
	dict := map[string]any{
		"KeepAlive":             true,
		"Label":                 "com.joneshong.scheduler.daemon",
		"ProgramArguments":      []string{"/bin/zsh", "-lc", "daemon.sh"},
		"StandardOutPath":       "/tmp/d.log",
		"StandardErrorPath":     "/tmp/d.err",
		"StartCalendarInterval": map[string]any{"Hour": 9, "Minute": 30},
		"ThrottleInterval":      10,
	}
	out := scheduleSyncEncodePlist(dict)
	if !strings.Contains(out, "<true/>") {
		t.Fatalf("expected <true/> for KeepAlive")
	}
	// Calendar dict nested with integer children
	if !strings.Contains(out, "<key>Hour</key>") ||
		!strings.Contains(out, "<integer>9</integer>") ||
		!strings.Contains(out, "<integer>30</integer>") {
		t.Fatalf("calendar dict mis-encoded:\n%s", out)
	}
}

func TestScheduleSyncXMLEscape(t *testing.T) {
	if got := scheduleSyncXMLEscape(`echo "a<b & c>d"`); got != `echo "a&lt;b &amp; c&gt;d"` {
		t.Fatalf("XML escape mismatch: %q", got)
	}
	// Quotes must NOT be escaped (plistlib parity).
	if got := scheduleSyncXMLEscape(`it's ok`); got != `it's ok` {
		t.Fatalf("apostrophe must not be escaped: %q", got)
	}
}

func TestScheduleSyncBuildScheduleDaemonDefault(t *testing.T) {
	job := map[string]any{
		"type":     "daemon",
		"schedule": map[string]any{"run_at_load": true},
	}
	s := scheduleSyncBuildSchedule(job)
	if v, _ := s["keep_alive"].(bool); !v {
		t.Fatalf("daemon should inject keep_alive=true, got %v", s["keep_alive"])
	}
	// Original map must not be mutated.
	if _, exists := job["schedule"].(map[string]any)["keep_alive"]; exists {
		t.Fatalf("original schedule must not be mutated")
	}
}

func TestScheduleSyncBuildSchedulePeriodicNoKeepAlive(t *testing.T) {
	job := map[string]any{
		"type":     "periodic",
		"schedule": map[string]any{"interval": 300},
	}
	s := scheduleSyncBuildSchedule(job)
	if _, exists := s["keep_alive"]; exists {
		t.Fatalf("periodic should not auto-set keep_alive")
	}
}

func TestScheduleSyncRegistryRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "registry.json")

	entries := []map[string]any{
		{"name": "job1", "enabled": true},
		{"name": "job2", "enabled": false},
	}
	if err := scheduleSyncWriteRegistry(path, entries); err != nil {
		t.Fatalf("write: %v", err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	// Python style: indent=2, no trailing newline.
	if strings.HasSuffix(string(data), "\n") {
		t.Fatalf("registry should not end with newline")
	}
	if !strings.Contains(string(data), `"name": "job1"`) {
		t.Fatalf("missing job1 in registry:\n%s", data)
	}
	// Round-trip parse
	var out []map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(out) != 2 || out[0]["name"] != "job1" {
		t.Fatalf("round-trip mismatch: %v", out)
	}
}

func TestScheduleSyncToInt(t *testing.T) {
	cases := []struct {
		v    any
		want int
		ok   bool
	}{
		{300, 300, true},
		{int64(420), 420, true},
		{float64(9), 9, true},
		{"bad", 0, false},
		{nil, 0, false},
	}
	for _, c := range cases {
		got, ok := scheduleSyncToInt(c.v)
		if got != c.want || ok != c.ok {
			t.Errorf("toInt(%v)=(%d,%v) want (%d,%v)", c.v, got, ok, c.want, c.ok)
		}
	}
}

func TestScheduleSyncRemoveJobNotFound(t *testing.T) {
	// Redirect HOME to a temp dir so we operate on an empty registry.
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	err := scheduleSyncRemoveJob("nonexistent")
	if err == nil {
		t.Fatal("expected error for missing job")
	}
	if !strings.Contains(err.Error(), "not found") {
		t.Fatalf("unexpected error: %v", err)
	}
}
