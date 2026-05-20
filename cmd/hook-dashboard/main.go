// hook-dashboard: HTTP dashboard for hook events.
//
// Reads events from ~/.hook-observatory/spool/events.jsonl (current source of
// truth, written by hook-dispatcher) and serves stats + event list via REST API
// plus a single-page HTML viewer.
//
// MVP (Phase 1 vertical slice 2026-05-16):
//   - In-memory aggregation from spool jsonl on each request (no DB yet)
//   - Endpoints: /api/health /api/stats/summary /api/stats/all
//                /api/stats/by-event /api/stats/by-tool /api/stats/by-session
//                /api/stats/timeline /api/events
//   - Single embedded vanilla HTML page with table + stats cards
//
// Roadmap (HANDOFF.md):
//   - Phase 2: spool drainer -> PostgreSQL hook_observatory.events schema
//   - Phase 3: embed React build with recharts
//   - Phase 4: cookie auth + i18n
package main

import (
	"embed"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed static
var staticFS embed.FS

const (
	defaultAddr     = "127.0.0.1:10100"
	defaultSpoolDir = "~/.hook-observatory/spool"
	cacheTTL        = 5 * time.Second
)

type event struct {
	EventType string                 `json:"event_type"`
	TS        string                 `json:"ts"`
	Data      map[string]interface{} `json:"data"`
}

type cache struct {
	mu     sync.RWMutex
	events []event
	loaded time.Time
}

var c = &cache{}

func expandSpoolDir(p string) string {
	if strings.HasPrefix(p, "~/") {
		home, _ := os.UserHomeDir()
		return filepath.Join(home, p[2:])
	}
	return p
}

func loadEvents(spoolDir string) ([]event, error) {
	c.mu.RLock()
	if time.Since(c.loaded) < cacheTTL && len(c.events) > 0 {
		evs := c.events
		c.mu.RUnlock()
		return evs, nil
	}
	c.mu.RUnlock()

	c.mu.Lock()
	defer c.mu.Unlock()

	entries, err := os.ReadDir(spoolDir)
	if err != nil {
		return nil, err
	}

	var files []string
	for _, e := range entries {
		name := e.Name()
		if strings.HasSuffix(name, ".jsonl") || strings.HasSuffix(name, ".processing") || strings.HasSuffix(name, ".draining") {
			files = append(files, filepath.Join(spoolDir, name))
		}
	}

	var evs []event
	for _, fp := range files {
		f, err := os.Open(fp)
		if err != nil {
			continue
		}
		dec := json.NewDecoder(f)
		for dec.More() {
			var ev event
			if err := dec.Decode(&ev); err != nil {
				break
			}
			evs = append(evs, ev)
		}
		f.Close()
	}

	sort.Slice(evs, func(i, j int) bool { return evs[i].TS < evs[j].TS })
	c.events = evs
	c.loaded = time.Now()
	return evs, nil
}

// ── Aggregations ─────────────────────────────────────────────

type summaryStats struct {
	Total           int `json:"total"`
	Today           int `json:"today"`
	UniqueSessions  int `json:"unique_sessions"`
}

type eventTypeStats struct {
	EventType string `json:"event_type"`
	Count     int    `json:"count"`
	Today     int    `json:"today"`
}

type toolStats struct {
	ToolName string `json:"tool_name"`
	Count    int    `json:"count"`
}

type sessionStats struct {
	SessionID  string `json:"session_id"`
	EventCount int    `json:"event_count"`
	FirstSeen  string `json:"first_seen"`
	LastSeen   string `json:"last_seen"`
}

type timelineBucket struct {
	Bucket string `json:"bucket"`
	Count  int    `json:"count"`
}

type allStats struct {
	Summary  summaryStats     `json:"summary"`
	ByEvent  []eventTypeStats `json:"by_event"`
	ByTool   []toolStats      `json:"by_tool"`
	Sessions []sessionStats   `json:"sessions"`
	Timeline []timelineBucket `json:"timeline"`
}

func isToday(ts string, cutoff time.Time) bool {
	t, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		return false
	}
	return t.After(cutoff)
}

func computeSummary(evs []event) summaryStats {
	cutoff := time.Now().Add(-24 * time.Hour)
	sessions := map[string]struct{}{}
	today := 0
	for _, e := range evs {
		if sid, ok := e.Data["session_id"].(string); ok && sid != "" {
			sessions[sid] = struct{}{}
		}
		if isToday(e.TS, cutoff) {
			today++
		}
	}
	return summaryStats{Total: len(evs), Today: today, UniqueSessions: len(sessions)}
}

func computeByEvent(evs []event) []eventTypeStats {
	cutoff := time.Now().Add(-24 * time.Hour)
	counts := map[string]int{}
	todays := map[string]int{}
	for _, e := range evs {
		counts[e.EventType]++
		if isToday(e.TS, cutoff) {
			todays[e.EventType]++
		}
	}
	out := make([]eventTypeStats, 0, len(counts))
	for k, v := range counts {
		out = append(out, eventTypeStats{EventType: k, Count: v, Today: todays[k]})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Count > out[j].Count })
	return out
}

func computeByTool(evs []event, limit int) []toolStats {
	counts := map[string]int{}
	for _, e := range evs {
		if name, ok := e.Data["tool_name"].(string); ok && name != "" {
			counts[name]++
		}
	}
	out := make([]toolStats, 0, len(counts))
	for k, v := range counts {
		out = append(out, toolStats{ToolName: k, Count: v})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Count > out[j].Count })
	if len(out) > limit {
		out = out[:limit]
	}
	return out
}

func computeBySession(evs []event, limit int) []sessionStats {
	type agg struct {
		count int
		first string
		last  string
	}
	m := map[string]*agg{}
	for _, e := range evs {
		sid, _ := e.Data["session_id"].(string)
		if sid == "" {
			continue
		}
		a, ok := m[sid]
		if !ok {
			a = &agg{first: e.TS, last: e.TS}
			m[sid] = a
		}
		a.count++
		if e.TS < a.first {
			a.first = e.TS
		}
		if e.TS > a.last {
			a.last = e.TS
		}
	}
	out := make([]sessionStats, 0, len(m))
	for k, v := range m {
		out = append(out, sessionStats{SessionID: k, EventCount: v.count, FirstSeen: v.first, LastSeen: v.last})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].LastSeen > out[j].LastSeen })
	if len(out) > limit {
		out = out[:limit]
	}
	return out
}

func computeTimeline(evs []event, granularity string, since time.Time) []timelineBucket {
	counts := map[string]int{}
	for _, e := range evs {
		t, err := time.Parse(time.RFC3339, e.TS)
		if err != nil || t.Before(since) {
			continue
		}
		var bucket string
		switch granularity {
		case "minute":
			bucket = t.Format("2006-01-02 15:04:00")
		case "day":
			bucket = t.Format("2006-01-02")
		default:
			bucket = t.Format("2006-01-02 15:00:00")
		}
		counts[bucket]++
	}
	out := make([]timelineBucket, 0, len(counts))
	for k, v := range counts {
		out = append(out, timelineBucket{Bucket: k, Count: v})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Bucket < out[j].Bucket })
	return out
}

// ── Handlers ─────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func newHandler(spoolDir string) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		entries, _ := os.ReadDir(spoolDir)
		pending := 0
		for _, e := range entries {
			n := e.Name()
			if strings.HasSuffix(n, ".jsonl") || strings.HasSuffix(n, ".draining") {
				pending++
			}
		}
		writeJSON(w, 200, map[string]interface{}{
			"status":                  "ok",
			"spool_dir":               spoolDir,
			"total_events_processed":  0,
			"pending_files":           pending,
		})
	})

	mux.HandleFunc("/api/stats/summary", func(w http.ResponseWriter, r *http.Request) {
		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, computeSummary(evs))
	})

	mux.HandleFunc("/api/stats/by-event", func(w http.ResponseWriter, r *http.Request) {
		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, computeByEvent(evs))
	})

	mux.HandleFunc("/api/stats/by-tool", func(w http.ResponseWriter, r *http.Request) {
		limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
		if limit <= 0 || limit > 100 {
			limit = 20
		}
		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, computeByTool(evs, limit))
	})

	mux.HandleFunc("/api/stats/by-session", func(w http.ResponseWriter, r *http.Request) {
		limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
		if limit <= 0 || limit > 100 {
			limit = 20
		}
		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, computeBySession(evs, limit))
	})

	mux.HandleFunc("/api/stats/timeline", func(w http.ResponseWriter, r *http.Request) {
		gran := r.URL.Query().Get("granularity")
		if gran == "" {
			gran = "hour"
		}
		rangeStr := r.URL.Query().Get("range")
		if rangeStr == "" {
			rangeStr = "7d"
		}
		dur := parseRange(rangeStr)
		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, computeTimeline(evs, gran, time.Now().Add(-dur)))
	})

	mux.HandleFunc("/api/stats/all", func(w http.ResponseWriter, r *http.Request) {
		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, allStats{
			Summary:  computeSummary(evs),
			ByEvent:  computeByEvent(evs),
			ByTool:   computeByTool(evs, 20),
			Sessions: computeBySession(evs, 20),
			Timeline: computeTimeline(evs, "hour", time.Now().Add(-7*24*time.Hour)),
		})
	})

	mux.HandleFunc("/api/events", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		limit, _ := strconv.Atoi(q.Get("limit"))
		if limit <= 0 || limit > 500 {
			limit = 100
		}
		offset, _ := strconv.Atoi(q.Get("offset"))
		if offset < 0 {
			offset = 0
		}
		typeFilter := q.Get("event_type")
		sessFilter := q.Get("session_id")
		toolFilter := q.Get("tool_name")

		evs, err := loadEvents(spoolDir)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		filtered := make([]event, 0, len(evs))
		for _, e := range evs {
			if typeFilter != "" && e.EventType != typeFilter {
				continue
			}
			if sessFilter != "" {
				sid, _ := e.Data["session_id"].(string)
				if sid != sessFilter {
					continue
				}
			}
			if toolFilter != "" {
				name, _ := e.Data["tool_name"].(string)
				if name != toolFilter {
					continue
				}
			}
			filtered = append(filtered, e)
		}

		// newest first
		sort.Slice(filtered, func(i, j int) bool { return filtered[i].TS > filtered[j].TS })

		total := len(filtered)
		end := offset + limit
		if end > total {
			end = total
		}
		if offset > total {
			offset = total
		}
		writeJSON(w, 200, map[string]interface{}{
			"items":  filtered[offset:end],
			"total":  total,
			"limit":  limit,
			"offset": offset,
		})
	})

	// Serve embedded static SPA at root.
	sub, err := fs.Sub(staticFS, "static")
	if err != nil {
		log.Fatalf("embed static failed: %v", err)
	}
	mux.Handle("/", http.FileServer(http.FS(sub)))

	return mux
}

func parseRange(s string) time.Duration {
	if len(s) < 2 {
		return 7 * 24 * time.Hour
	}
	n, err := strconv.Atoi(s[:len(s)-1])
	if err != nil {
		return 7 * 24 * time.Hour
	}
	switch s[len(s)-1] {
	case 'h':
		return time.Duration(n) * time.Hour
	case 'd':
		return time.Duration(n) * 24 * time.Hour
	case 'm':
		return time.Duration(n) * time.Minute
	}
	return 7 * 24 * time.Hour
}

func main() {
	addr := flag.String("addr", defaultAddr, "listen address")
	spoolDir := flag.String("spool", defaultSpoolDir, "spool directory")
	flag.Parse()

	dir := expandSpoolDir(*spoolDir)
	if _, err := os.Stat(dir); err != nil {
		fmt.Fprintf(os.Stderr, "spool dir not found: %s\n", dir)
		os.Exit(1)
	}

	srv := &http.Server{
		Addr:         *addr,
		Handler:      newHandler(dir),
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
	}

	log.Printf("[hook-dashboard] listen %s spool=%s", *addr, dir)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("listen: %v", err)
	}
}
