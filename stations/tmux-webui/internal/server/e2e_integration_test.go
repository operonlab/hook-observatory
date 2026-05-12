//go:build tmux_integration

package server_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/operonlab/tmux-webui/internal/config"
	"github.com/operonlab/tmux-webui/internal/server"
	"github.com/operonlab/tmux-webui/internal/tmuxctl"
)

// TestE2E_WsReceivesInitialFrames connects a real WebSocket against a real
// tmux server and verifies the first frames the client gets after upgrade.
//
// Skipped automatically when no tmux session is reachable.
//
// Run with:  go test -tags=tmux_integration ./internal/server -v -run TestE2E
func TestE2E_WsReceivesInitialFrames(t *testing.T) {
	cfg := config.Defaults()
	cfg.PollInterval = 0.4
	cfg.MetricsInterval = 5.0
	cfg.CaptureLines = 50

	tx := tmuxctl.New()
	probeCtx, probeCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer probeCancel()
	sessions, err := tx.ListSessions(probeCtx)
	if err != nil || len(sessions) == 0 {
		t.Skip("no tmux session; skipping e2e test")
	}
	sessionName := sessions[0].Name

	srv := server.New(&cfg, tx)
	defer srv.Close()

	httpSrv := httptest.NewServer(srv.Mux())
	defer httpSrv.Close()

	wsURL, _ := url.Parse(httpSrv.URL)
	wsURL.Scheme = "ws"
	wsURL.Path = "/ws"
	wsURL.RawQuery = "session=" + sessionName

	dialCtx, dialCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer dialCancel()
	c, _, err := websocket.Dial(dialCtx, wsURL.String(), nil)
	if err != nil {
		t.Fatalf("ws dial: %v", err)
	}
	defer c.Close(websocket.StatusNormalClosure, "test done")

	// Read up to 6 frames within 4 seconds; expect to see windows + panes at minimum.
	seen := map[string]bool{}
	deadline := time.Now().Add(4 * time.Second)
	for i := 0; i < 8 && time.Now().Before(deadline); i++ {
		readCtx, readCancel := context.WithTimeout(context.Background(), 3*time.Second)
		_, raw, err := c.Read(readCtx)
		readCancel()
		if err != nil {
			break
		}
		var env map[string]any
		if err := json.Unmarshal(raw, &env); err != nil {
			continue
		}
		if typ, ok := env["type"].(string); ok {
			seen[typ] = true
		}
	}

	for _, want := range []string{"windows", "panes"} {
		if !seen[want] {
			t.Errorf("expected to receive %q frame; saw %v", want, seen)
		}
	}
	t.Logf("ws frame types seen: %v", seen)
}

// TestE2E_AllMajorRoutes spot-checks every public HTTP route against a live
// server backed by a real tmux server.
func TestE2E_AllMajorRoutes(t *testing.T) {
	cfg := config.Defaults()
	tx := tmuxctl.New()
	probeCtx, probeCancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer probeCancel()
	if _, err := tx.ListSessions(probeCtx); err != nil {
		t.Skip("no tmux server; skipping")
	}

	srv := server.New(&cfg, tx)
	defer srv.Close()
	httpSrv := httptest.NewServer(srv.Mux())
	defer httpSrv.Close()

	cases := []struct {
		method string
		path   string
		want   int
	}{
		{"GET", "/", http.StatusOK},
		{"GET", "/sw.js", http.StatusOK},
		{"GET", "/manifest.json", http.StatusOK},
		{"GET", "/icon-192.png", http.StatusOK},
		{"GET", "/static/css/main.css", http.StatusOK},
		{"GET", "/api/version", http.StatusOK},
		{"GET", "/api/sessions", http.StatusOK},
		{"GET", "/api/metrics", http.StatusOK},
		{"GET", "/api/autocomplete?q=test", http.StatusOK},
		{"POST", "/api/relay", http.StatusNotImplemented}, // disabled by default
		{"GET", "/api/tts/nonexistent", http.StatusNotFound},
	}
	for _, tc := range cases {
		t.Run(tc.method+"_"+tc.path, func(t *testing.T) {
			req, _ := http.NewRequest(tc.method, httpSrv.URL+tc.path, strings.NewReader(""))
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatalf("%s %s: %v", tc.method, tc.path, err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != tc.want {
				t.Errorf("%s %s: status %d; want %d", tc.method, tc.path, resp.StatusCode, tc.want)
			}
		})
	}
}

// TestE2E_VersionEndpoint asserts /api/version returns the buildinfo struct shape.
func TestE2E_VersionEndpoint(t *testing.T) {
	cfg := config.Defaults()
	tx := tmuxctl.New()
	srv := server.New(&cfg, tx)
	defer srv.Close()
	httpSrv := httptest.NewServer(srv.Mux())
	defer httpSrv.Close()

	resp, err := http.Get(httpSrv.URL + "/api/version")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"version", "git_hash", "build_date"} {
		if _, ok := body[key]; !ok {
			t.Errorf("missing key %q in /api/version response: %v", key, body)
		}
	}
}
