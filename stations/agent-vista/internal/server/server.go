// Package server implements the HTTP/WebSocket server for Agent Vista.
package server

import (
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"

	"nhooyr.io/websocket"

	"github.com/joneshong/agent-vista/internal/broker"
	"github.com/joneshong/agent-vista/internal/protocol"
)

// Server serves the WebSocket endpoint and REST API.
type Server struct {
	broker     *broker.Broker
	tracker    *AgentTracker
	layoutDB   *LayoutDB        // optional; nil when no database URL configured
	monitor    *ProcessMonitor   // optional; nil when monitoring disabled
	addr       string
	verbose    bool
	frontendFS fs.FS // embedded frontend (nil in dev mode)
}

// New creates a new HTTP/WS server with an integrated AgentTracker.
// frontendFS may be nil; when non-nil, the server serves the embedded SPA.
func New(b *broker.Broker, addr string, verbose bool, frontendFS fs.FS) *Server {
	return &Server{
		broker:     b,
		tracker:    NewAgentTracker(),
		addr:       addr,
		verbose:    verbose,
		frontendFS: frontendFS,
	}
}

// SetProcessMonitor attaches the process monitor for the /api/resources endpoint.
func (s *Server) SetProcessMonitor(pm *ProcessMonitor) {
	s.monitor = pm
}

// SetLayoutDB attaches an optional PostgreSQL-backed layout store to the server.
// When set, the /api/layout endpoints use it; otherwise they return 503.
func (s *Server) SetLayoutDB(ldb *LayoutDB) {
	s.layoutDB = ldb
}

// Tracker returns the server's AgentTracker so callers can feed events into it.
func (s *Server) Tracker() *AgentTracker {
	return s.tracker
}

// Start begins listening. Blocks until ctx is cancelled or an error occurs.
func (s *Server) Start(ctx context.Context) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", s.handleWS)
	mux.HandleFunc("/api/health", s.handleHealth)
	mux.HandleFunc("/api/agents", s.handleAgents)
	mux.HandleFunc("/api/stats", s.handleStats)
	mux.HandleFunc("/api/events", s.handleEvents)
	mux.HandleFunc("/api/resources", s.handleResources)
	mux.HandleFunc("/api/layout", s.handleLayout)
	mux.HandleFunc("/api/layout/history", s.handleLayoutHistory)
	mux.HandleFunc("/api/layout/version/", s.handleLayoutVersion)

	// Serve custom sprite images from ~/.agent-vista/sprites/
	if home, err := os.UserHomeDir(); err == nil {
		spritesDir := home + "/.agent-vista/sprites"
		os.MkdirAll(spritesDir, 0o755)
		mux.Handle("/sprites/", http.StripPrefix("/sprites/", http.FileServer(http.Dir(spritesDir))))
		if s.verbose {
			log.Printf("[server] serving custom sprites from %s", spritesDir)
		}
	}

	// Serve embedded frontend SPA (production mode)
	if s.frontendFS != nil {
		mux.Handle("/", s.spaHandler())
		if s.verbose {
			log.Printf("[server] serving embedded frontend")
		}
	}

	srv := &http.Server{
		Addr:    s.addr,
		Handler: mux,
	}

	go func() {
		<-ctx.Done()
		srv.Shutdown(context.Background())
	}()

	log.Printf("[server] listening on %s", s.addr)
	return srv.ListenAndServe()
}

// spaHandler returns an http.Handler that serves the embedded frontend.
// For SPA routing, any path that doesn't match a real file serves index.html.
func (s *Server) spaHandler() http.Handler {
	fileServer := http.FileServer(http.FS(s.frontendFS))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Try to serve the exact file
		path := strings.TrimPrefix(r.URL.Path, "/")
		if path == "" {
			path = "index.html"
		}
		if _, err := fs.Stat(s.frontendFS, path); err == nil {
			fileServer.ServeHTTP(w, r)
			return
		}
		// Fallback: serve index.html for SPA client-side routing
		r.URL.Path = "/"
		fileServer.ServeHTTP(w, r)
	})
}

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true, // P0: allow all origins for local dev
	})
	if err != nil {
		log.Printf("[server] ws accept error: %v", err)
		return
	}
	defer conn.Close(websocket.StatusNormalClosure, "bye")

	ctx := r.Context()

	// Send init message with current agent states from tracker (exclude offline agents)
	allAgents := s.tracker.Agents()
	var visibleAgents []protocol.AgentState
	for _, a := range allAgents {
		if a.Status != protocol.StatusOffline {
			visibleAgents = append(visibleAgents, a)
		}
	}
	initMsg := protocol.WSMessage{
		Type: protocol.WSTypeInit,
		Init: &protocol.WSInit{Agents: visibleAgents},
	}
	if err := writeJSON(ctx, conn, initMsg); err != nil {
		return
	}

	// Subscribe to event broker
	subID, ch := s.broker.Subscribe(64)
	defer s.broker.Unsubscribe(subID)

	if s.verbose {
		log.Printf("[server] ws client connected (sub=%d)", subID)
	}

	// Forward events to client until disconnect
	for {
		select {
		case <-ctx.Done():
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			if err := writeJSON(ctx, conn, msg); err != nil {
				if s.verbose {
					log.Printf("[server] ws write error (sub=%d): %v", subID, err)
				}
				return
			}
		}
	}
}

// corsHeaders sets permissive CORS headers for local frontend dev server.
func corsHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == "OPTIONS" {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"status":      "ok",
		"subscribers": s.broker.SubscriberCount(),
	})
}

func (s *Server) handleAgents(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == "OPTIONS" {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s.tracker.Agents())
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == "OPTIONS" {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"total_events":    s.tracker.TotalEvents(),
		"active_sessions": s.tracker.ActiveSessionCount(),
		"subscribers":     s.broker.SubscriberCount(),
		"latest_seq":      s.tracker.LatestSeq(),
	})
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == "OPTIONS" {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	afterStr := r.URL.Query().Get("after")
	after, _ := strconv.ParseUint(afterStr, 10, 64)
	events := s.tracker.EventsSince(after)
	json.NewEncoder(w).Encode(events)
}

func (s *Server) handleResources(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == "OPTIONS" {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	if s.monitor == nil {
		json.NewEncoder(w).Encode([]protocol.ProcessInfo{})
		return
	}
	procs := s.monitor.LatestSnapshot()
	if procs == nil {
		procs = []protocol.ProcessInfo{}
	}
	json.NewEncoder(w).Encode(procs)
}

func writeJSON(ctx context.Context, conn *websocket.Conn, v any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return conn.Write(ctx, websocket.MessageText, data)
}

// handleLayout dispatches GET and PUT /api/layout.
//
//   - GET  returns the latest saved layout version, or 404 if none exists.
//   - PUT  accepts a LayoutData JSON body, saves a new version, and returns the row.
func (s *Server) handleLayout(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == http.MethodOptions {
		return
	}

	if s.layoutDB == nil {
		http.Error(w, `{"error":"database not configured"}`, http.StatusServiceUnavailable)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	switch r.Method {
	case http.MethodGet:
		row, err := s.layoutDB.GetLatest("default")
		if err != nil {
			log.Printf("[layout] GetLatest error: %v", err)
			http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
			return
		}
		if row == nil {
			http.Error(w, `{"error":"no layout saved"}`, http.StatusNotFound)
			return
		}
		json.NewEncoder(w).Encode(row)

	case http.MethodPut:
		body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1 MB limit
		if err != nil {
			http.Error(w, `{"error":"failed to read body"}`, http.StatusBadRequest)
			return
		}
		var data LayoutData
		if err := json.Unmarshal(body, &data); err != nil {
			http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
			return
		}
		row, err := s.layoutDB.SaveVersion("default", data)
		if err != nil {
			log.Printf("[layout] SaveVersion error: %v", err)
			http.Error(w, `{"error":"failed to save layout"}`, http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(row)

	default:
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

// handleLayoutHistory serves GET /api/layout/history — returns up to 50 versions.
func (s *Server) handleLayoutHistory(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == http.MethodOptions {
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	if s.layoutDB == nil {
		http.Error(w, `{"error":"database not configured"}`, http.StatusServiceUnavailable)
		return
	}

	rows, err := s.layoutDB.ListVersions("default", 50)
	if err != nil {
		log.Printf("[layout] ListVersions error: %v", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	if rows == nil {
		rows = []LayoutVersionRow{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(rows)
}

// handleLayoutVersion serves GET /api/layout/version/{v} — returns a specific version.
func (s *Server) handleLayoutVersion(w http.ResponseWriter, r *http.Request) {
	corsHeaders(w)
	if r.Method == http.MethodOptions {
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	if s.layoutDB == nil {
		http.Error(w, `{"error":"database not configured"}`, http.StatusServiceUnavailable)
		return
	}

	// Extract version number from path: /api/layout/version/{v}
	vStr := strings.TrimPrefix(r.URL.Path, "/api/layout/version/")
	v, err := strconv.Atoi(vStr)
	if err != nil || v < 1 {
		http.Error(w, `{"error":"invalid version number"}`, http.StatusBadRequest)
		return
	}

	row, err := s.layoutDB.GetVersion("default", v)
	if err != nil {
		log.Printf("[layout] GetVersion error: %v", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	if row == nil {
		http.Error(w, `{"error":"version not found"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(row)
}
