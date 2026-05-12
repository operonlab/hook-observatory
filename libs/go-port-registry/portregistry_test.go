package portregistry

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestLoadsAllServices(t *testing.T) {
	if got := len(Ports); got != 37 {
		t.Fatalf("expected 37 services from yaml, got %d", got)
	}
	if Host != "127.0.0.1" {
		t.Fatalf("Host = %q, want %q", Host, "127.0.0.1")
	}
}

func TestGetCore(t *testing.T) {
	svc, ok := Get("core")
	if !ok {
		t.Fatal("core service missing from registry")
	}
	if svc.Port != 10000 {
		t.Errorf("core.Port = %d, want 10000", svc.Port)
	}
	if got := svc.URL(); got != "http://127.0.0.1:10000" {
		t.Errorf("core.URL() = %q, want http://127.0.0.1:10000", got)
	}
	h, ok := svc.HealthURL()
	if !ok || h != "http://127.0.0.1:10000/health" {
		t.Errorf("core.HealthURL() = (%q, %t), want (http://127.0.0.1:10000/health, true)", h, ok)
	}
}

func TestGetMissing(t *testing.T) {
	if _, ok := Get("does-not-exist"); ok {
		t.Fatal("expected missing service to return false")
	}
}

func TestSentinelLegacyPort(t *testing.T) {
	s, ok := Get("sentinel")
	if !ok {
		t.Fatal("sentinel missing")
	}
	if s.Port != 4101 {
		t.Errorf("sentinel.Port = %d, want 4101", s.Port)
	}
	if s.HealthPath != "/api/sentinel/health" {
		t.Errorf("sentinel.HealthPath = %q, want /api/sentinel/health", s.HealthPath)
	}
}

func TestWorkbenchHasNoHealthURL(t *testing.T) {
	w, ok := Get("workbench")
	if !ok {
		t.Fatal("workbench missing")
	}
	if _, ok := w.HealthURL(); ok {
		t.Error("workbench.HealthURL() should be (\"\", false) when health_path empty")
	}
}

func TestByGroupCounts(t *testing.T) {
	cases := map[string]int{
		"core":          4,
		"docker":        7,
		"station-ai":    9,
		"station-infra": 8,
		"station-biz":   3,
		"third-party":   5,
		"frontend":      1,
	}
	for group, want := range cases {
		if got := len(ByGroup(group)); got != want {
			t.Errorf("ByGroup(%q) = %d services, want %d", group, got, want)
		}
	}
}

func TestURLHelperUsesRegistryPort(t *testing.T) {
	// "tts" is registered at 10201 — fallback port 9999 must be ignored.
	got := URL("tts", "/synthesize", 9999)
	want := "http://127.0.0.1:10201/synthesize"
	if got != want {
		t.Errorf("URL(tts) = %q, want %q", got, want)
	}
}

func TestURLHelperFallsBackOnMiss(t *testing.T) {
	got := URL("does-not-exist", "/x", 9999)
	want := "http://127.0.0.1:9999/x"
	if got != want {
		t.Errorf("URL(miss) = %q, want %q", got, want)
	}
}

func TestURLHelperEmptyPath(t *testing.T) {
	got := URL("core", "", 0)
	want := "http://127.0.0.1:10000"
	if got != want {
		t.Errorf("URL(core, \"\") = %q, want %q", got, want)
	}
}

// TestCodegenIsRerunnable invokes cmd/gen against a minimal yaml fixture and
// verifies it produces a parseable ports.go. This proves the "rerun on yaml
// change" contract: any edit to shared/schemas/port_registry.yaml that
// changes the byte content will, after `go generate ./...`, be reflected in
// ports.go.
func TestCodegenIsRerunnable(t *testing.T) {
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot locate test source")
	}
	pkgDir := filepath.Dir(thisFile)

	tmpDir := t.TempDir()
	yamlPath := filepath.Join(tmpDir, "mini.yaml")
	outPath := filepath.Join(tmpDir, "ports_gen.go")

	yamlBody := `host: 10.0.0.1
services:
  - name: alpha
    port: 11000
    group: test
    health_path: /alive
    env_var: ALPHA_URL
    nginx_path: ""
    optional: false
  - name: beta
    port: 11001
    group: test
    health_path: ""
    env_var: ""
    nginx_path: ""
    optional: true
`
	if err := os.WriteFile(yamlPath, []byte(yamlBody), 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	cmd := exec.Command("go", "run", "./cmd/gen")
	cmd.Dir = pkgDir
	cmd.Env = append(os.Environ(),
		"PORT_REGISTRY_YAML="+yamlPath,
		"PORT_REGISTRY_OUT="+outPath,
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("go generate failed: %v\n%s", err, out)
	}

	content, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("read generated: %v", err)
	}
	s := string(content)
	wantSubs := []string{
		`Host = "10.0.0.1"`,
		`Name: "alpha"`,
		`Port: 11000`,
		`HealthPath: "/alive"`,
		`EnvVar: "ALPHA_URL"`,
		`Name: "beta"`,
		`Optional: true`,
	}
	for _, sub := range wantSubs {
		if !strings.Contains(s, sub) {
			t.Errorf("generated file missing %q\n---\n%s", sub, s)
		}
	}
}
