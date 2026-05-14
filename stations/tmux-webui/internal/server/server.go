// Package server wires the HTTP routes for tmux-webui.
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/operonlab/tmux-webui/internal/autocomplete"
	"github.com/operonlab/tmux-webui/internal/buildinfo"
	"github.com/operonlab/tmux-webui/internal/config"
	"github.com/operonlab/tmux-webui/internal/metrics"
	"github.com/operonlab/tmux-webui/internal/prefix"
	"github.com/operonlab/tmux-webui/internal/pwa"
	"github.com/operonlab/tmux-webui/internal/relay"
	"github.com/operonlab/tmux-webui/internal/tmuxctl"
	"github.com/operonlab/tmux-webui/internal/tts"
	"github.com/operonlab/tmux-webui/internal/upload"
	"github.com/operonlab/tmux-webui/internal/ws"
)

type Server struct {
	cfg    *config.Config
	tx     *tmuxctl.Client
	hub    *ws.Hub
	ac     *autocomplete.Engine
	prov   metrics.Provider
	upload *upload.Handler
	tts    *tts.Store
	relay  *relay.Dispatcher // nil when relay disabled
}

func New(cfg *config.Config, tx *tmuxctl.Client) *Server {
	pc := prefix.New(tx)

	var prov metrics.Provider = metrics.NewStub()
	if cfg.Metrics.Provider == "http" && cfg.Metrics.URL != "" {
		prov = metrics.NewHTTP(cfg.Metrics.URL)
	}

	hub := ws.NewHub(cfg, tx, pc, prov)

	ac := autocomplete.New(autocomplete.Options{ClaudeDir: cfg.Autocomplete.ClaudeDir})

	rly, _ := relay.New(cfg.Relay.PaneScript, cfg.Relay.RelayScript, cfg.Relay.SignalDir)
	// New returns nil when both scripts are empty (disabled by default for OSS).
	// Real config errors (paths set but files missing) are logged and treated as disabled.

	return &Server{
		cfg:    cfg,
		tx:     tx,
		hub:    hub,
		ac:     ac,
		prov:   prov,
		upload: upload.New(cfg.UploadDir, 50<<20),
		tts:    tts.NewStore(),
		relay:  rly,
	}
}

func (s *Server) Close() {
	if s.ac != nil {
		s.ac.Close()
	}
}

func (s *Server) Mux() http.Handler {
	mux := http.NewServeMux()

	// PWA shell
	mux.Handle("GET /{$}", pwa.IndexHandler())
	mux.Handle("GET /sw.js", pwa.SwjsHandler())
	mux.Handle("GET /manifest.json", pwa.AssetFile("manifest.json", "application/manifest+json"))
	mux.Handle("GET /icon-192.svg", pwa.AssetFile("icon-192.svg", "image/svg+xml"))
	mux.Handle("GET /icon-512.svg", pwa.AssetFile("icon-512.svg", "image/svg+xml"))
	mux.Handle("GET /icon-192.png", pwa.AssetFile("icon-192.png", "image/png"))
	mux.Handle("GET /icon-512.png", pwa.AssetFile("icon-512.png", "image/png"))
	mux.Handle("GET /static/", pwa.StaticFS())

	// Workshop Py version is reverse-proxied behind nginx with /apps/tmux/
	// prefix; the embedded index.html still references those URLs. Serve
	// the same files at both paths so the OSS binary works without needing
	// to edit the frontend HTML.
	mux.Handle("GET /apps/tmux/manifest.json", pwa.AssetFile("manifest.json", "application/manifest+json"))
	mux.Handle("GET /apps/tmux/icon-192.svg", pwa.AssetFile("icon-192.svg", "image/svg+xml"))
	mux.Handle("GET /apps/tmux/icon-512.svg", pwa.AssetFile("icon-512.svg", "image/svg+xml"))
	mux.Handle("GET /apps/tmux/icon-192.png", pwa.AssetFile("icon-192.png", "image/png"))
	mux.Handle("GET /apps/tmux/icon-512.png", pwa.AssetFile("icon-512.png", "image/png"))
	mux.Handle("GET /favicon.ico", pwa.AssetFile("icon-192.png", "image/png"))

	// Read-only tmux queries
	mux.HandleFunc("GET /api/sessions", s.handleListSessions)
	mux.HandleFunc("GET /api/sessions/{name}/panes", s.handleListPanes)
	mux.HandleFunc("GET /api/sessions/{name}/windows", s.handleListWindows)

	// Build/version info
	mux.HandleFunc("GET /api/version", s.handleVersion)

	// Metrics (REST snapshot for non-ws polling)
	mux.HandleFunc("GET /api/metrics", s.handleMetrics)

	// WebSocket
	mux.Handle("/ws", s.hub.UpgradeHandler())

	// Autocomplete
	mux.HandleFunc("GET /api/autocomplete", s.handleAutocomplete)
	mux.HandleFunc("GET /api/autocomplete/refresh", s.handleAutocompleteRefresh)

	// Upload (50MB cap inside handler)
	mux.Handle("POST /api/upload", s.upload.HTTP())

	// TTS push + serve
	mux.Handle("POST /api/tts/push", s.tts.PushHandler(s.hub.BroadcastTTS))
	mux.Handle("GET /api/tts/{id}", s.tts.GetHandler())

	// Relay (optional; nil when scripts not configured)
	if s.relay != nil {
		mux.Handle("POST /api/relay", s.relay.DispatchHandler())
		mux.Handle("GET /api/relay/check", s.relay.CheckHandler())
	} else {
		mux.HandleFunc("/api/relay", notImplemented("/api/relay — disabled (config.relay scripts not set)"))
		mux.HandleFunc("/api/relay/check", notImplemented("/api/relay/check — disabled (config.relay scripts not set)"))
	}

	return logRequests(mux)
}

func (s *Server) handleListSessions(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	sessions, err := s.tx.ListSessions(ctx)
	if err != nil || sessions == nil {
		writeJSON(w, http.StatusOK, []any{})
		return
	}
	writeJSON(w, http.StatusOK, sessions)
}

func (s *Server) handleListPanes(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	panes, err := s.tx.ListPanes(ctx, name)
	if err != nil || panes == nil {
		writeJSON(w, http.StatusOK, []any{})
		return
	}
	writeJSON(w, http.StatusOK, panes)
}

func (s *Server) handleListWindows(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	windows, err := s.tx.ListWindows(ctx, name)
	if err != nil || windows == nil {
		writeJSON(w, http.StatusOK, []any{})
		return
	}
	writeJSON(w, http.StatusOK, windows)
}

func (s *Server) handleVersion(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{
		"version":    buildinfo.Version,
		"git_hash":   buildinfo.GitHash,
		"build_date": buildinfo.BuildDate,
	})
}

func (s *Server) handleMetrics(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	writeJSON(w, http.StatusOK, s.prov.Collect(ctx))
}

func (s *Server) handleAutocomplete(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query().Get("q")
	t := r.URL.Query().Get("type")
	items := s.ac.Complete(q, t)
	if items == nil {
		items = []autocomplete.Item{}
	}
	writeJSON(w, http.StatusOK, items)
}

func (s *Server) handleAutocompleteRefresh(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.ac.Refresh())
}

func notImplemented(reason string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, reason, http.StatusNotImplemented)
	}
}

func writeJSON(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: 200}
		next.ServeHTTP(rec, r)
		fmt.Printf("%s %s %d %s\n", r.Method, r.URL.Path, rec.status, time.Since(start))
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

// Unwrap exposes the underlying ResponseWriter so http.NewResponseController
// (used by coder/websocket for Hijack) can reach the real Hijacker. Without
// this, WS upgrade returns 501 because the middleware hides the interface.
func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }
