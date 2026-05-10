// Package server wires the HTTP routes for tmux-webui.
//
// v0 covers the read-only HTTP surface that the frontend hits before
// the WebSocket connects: GET /api/sessions, /api/sessions/{name}/panes,
// /api/sessions/{name}/windows, plus the PWA shell (index, sw.js,
// manifest, icons, /static/*).
//
// Stubs (501 Not Implemented) reserve the slots for routes that need
// later phases: /ws, /api/autocomplete, /api/upload, /api/relay,
// /api/relay/check, /api/tts/push, /api/tts/{id}.
//
// Uses Go 1.22+ ServeMux pattern routes — no third-party HTTP framework.
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/operonlab/tmux-webui/internal/buildinfo"
	"github.com/operonlab/tmux-webui/internal/config"
	"github.com/operonlab/tmux-webui/internal/pwa"
	"github.com/operonlab/tmux-webui/internal/tmuxctl"
)

type Server struct {
	cfg *config.Config
	tx  *tmuxctl.Client
}

func New(cfg *config.Config, tx *tmuxctl.Client) *Server {
	return &Server{cfg: cfg, tx: tx}
}

// Mux returns the configured HTTP handler.
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

	// Read-only tmux queries
	mux.HandleFunc("GET /api/sessions", s.handleListSessions)
	mux.HandleFunc("GET /api/sessions/{name}/panes", s.handleListPanes)
	mux.HandleFunc("GET /api/sessions/{name}/windows", s.handleListWindows)

	// Build/version info — useful for the frontend to detect deploys.
	mux.HandleFunc("GET /api/version", s.handleVersion)

	// Stubs (later phases)
	mux.HandleFunc("/ws", notImplemented("/ws — WebSocket pending Phase 1.8"))
	mux.HandleFunc("/api/autocomplete", notImplemented("/api/autocomplete — pending Phase 1.7"))
	mux.HandleFunc("/api/autocomplete/refresh", notImplemented("/api/autocomplete/refresh — pending Phase 1.7"))
	mux.HandleFunc("/api/upload", notImplemented("/api/upload — pending Phase 1.6"))
	mux.HandleFunc("/api/relay", notImplemented("/api/relay — optional, pending Phase 1.9"))
	mux.HandleFunc("/api/relay/check", notImplemented("/api/relay/check — optional, pending Phase 1.9"))
	mux.HandleFunc("/api/tts/push", notImplemented("/api/tts/push — pending Phase 1.6"))
	mux.HandleFunc("/api/tts/{id}", notImplemented("/api/tts — pending Phase 1.6"))

	return logRequests(mux)
}

func (s *Server) handleListSessions(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	sessions, err := s.tx.ListSessions(ctx)
	if err != nil {
		writeJSON(w, http.StatusOK, []any{})
		return
	}
	if sessions == nil {
		sessions = []tmuxctl.Session{}
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

// logRequests is a minimal access log middleware (stdlib log via fmt to stderr).
// Replaced with structured slog in a later phase.
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
