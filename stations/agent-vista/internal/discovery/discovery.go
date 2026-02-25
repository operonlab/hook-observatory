// Package discovery periodically scans the filesystem for active CLI transcript
// sessions across Claude Code, Codex CLI, and Gemini CLI.
package discovery

import (
	"context"
	"log"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

const (
	// activeWindow is the maximum age of a file to be considered actively working.
	activeWindow = 20 * time.Minute
	// restingWindow is the maximum age to be considered resting (idle but not offline).
	restingWindow = 60 * time.Minute
)

// SessionFreshness indicates how recently a transcript file was modified.
type SessionFreshness int

const (
	FreshActive  SessionFreshness = iota // modified within activeWindow
	FreshResting                         // modified within restingWindow but not activeWindow
)

// DiscoveredSession holds a transcript path and its freshness category.
type DiscoveredSession struct {
	Path      string
	Freshness SessionFreshness
}

// Discovery periodically scans for active CLI transcript sessions.
type Discovery struct {
	interval time.Duration
	onFound  func(path string) // callback when new transcript file is found
	known    map[string]bool   // already-discovered paths
	mu       sync.RWMutex
	verbose  bool
	homeDir  string // resolved once at construction; empty triggers os.UserHomeDir
}

// New creates a new Discovery scanner.
// interval controls how often the scan loop runs.
// onFound is called once for each newly discovered transcript file (must be safe for concurrent use).
// verbose enables detailed logging of scan results.
func New(interval time.Duration, onFound func(path string), verbose bool) *Discovery {
	home, err := os.UserHomeDir()
	if err != nil {
		// Fallback: scanning will produce no results but won't crash.
		log.Printf("[discovery] warning: cannot resolve home directory: %v", err)
	}

	return &Discovery{
		interval: interval,
		onFound:  onFound,
		known:    make(map[string]bool),
		verbose:  verbose,
		homeDir:  home,
	}
}

// Start runs the scan loop, blocking until ctx is cancelled.
func (d *Discovery) Start(ctx context.Context) error {
	// Run an initial scan immediately.
	d.ScanOnce()

	ticker := time.NewTicker(d.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			d.ScanOnce()
		}
	}
}

// ScanOnce performs a single scan across all CLI transcript directories.
// Returns the list of newly discovered paths (paths not previously known).
func (d *Discovery) ScanOnce() []string {
	if d.homeDir == "" {
		return nil
	}

	var found []DiscoveredSession
	found = append(found, d.scanClaude()...)
	found = append(found, d.scanCodex()...)
	found = append(found, d.scanGemini()...)

	// Deduplicate against known and notify.
	var newPaths []string
	d.mu.Lock()
	for _, ds := range found {
		if !d.known[ds.Path] {
			d.known[ds.Path] = true
			newPaths = append(newPaths, ds.Path)
		}
	}
	d.mu.Unlock()

	for _, p := range newPaths {
		if d.verbose {
			log.Printf("[discovery] new session: %s", p)
		}
		if d.onFound != nil {
			d.onFound(p)
		}
	}

	if d.verbose {
		log.Printf("[discovery] scan complete: %d scanned, %d new", len(found), len(newPaths))
	}

	return newPaths
}

// KnownSessions returns a sorted list of all previously discovered transcript paths.
func (d *Discovery) KnownSessions() []string {
	d.mu.RLock()
	defer d.mu.RUnlock()

	paths := make([]string, 0, len(d.known))
	for p := range d.known {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	return paths
}

// --- CLI-specific scanners ---

// scanClaude looks for Claude Code JSONL transcripts modified within the resting window.
// Pattern: ~/.claude/projects/*/*.jsonl (sessions are directly under project dirs)
func (d *Discovery) scanClaude() []DiscoveredSession {
	pattern := filepath.Join(d.homeDir, ".claude", "projects", "*", "*.jsonl")
	return d.globWithFreshness(pattern)
}

// scanCodex looks for Codex CLI JSONL transcripts modified within the resting window.
// Pattern: ~/.codex/sessions/YYYY/MM/DD/*.jsonl
func (d *Discovery) scanCodex() []DiscoveredSession {
	now := time.Now()
	var candidates []string

	for _, day := range []time.Time{now, now.AddDate(0, 0, -1)} {
		dir := filepath.Join(
			d.homeDir, ".codex", "sessions",
			day.Format("2006"), day.Format("01"), day.Format("02"),
		)
		pattern := filepath.Join(dir, "*.jsonl")
		matches, err := filepath.Glob(pattern)
		if err != nil {
			continue
		}
		candidates = append(candidates, matches...)
	}

	// Apply mtime freshness filter (same as Claude/Gemini)
	return d.filterByFreshness(candidates)
}

// scanGemini looks for Gemini CLI JSON transcripts modified within the resting window.
// Pattern: ~/.gemini/tmp/*/chats/*.json
func (d *Discovery) scanGemini() []DiscoveredSession {
	pattern := filepath.Join(d.homeDir, ".gemini", "tmp", "*", "chats", "*.json")
	return d.globWithFreshness(pattern)
}

// globWithFreshness expands a glob pattern and categorizes matches by freshness.
func (d *Discovery) globWithFreshness(pattern string) []DiscoveredSession {
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return nil
	}
	return d.filterByFreshness(matches)
}

// filterByFreshness categorizes paths into active/resting based on mtime.
// Paths older than restingWindow are excluded entirely.
func (d *Discovery) filterByFreshness(paths []string) []DiscoveredSession {
	now := time.Now()
	activeCutoff := now.Add(-activeWindow)
	restingCutoff := now.Add(-restingWindow)

	var results []DiscoveredSession
	for _, p := range paths {
		info, err := os.Stat(p)
		if err != nil {
			continue
		}
		mtime := info.ModTime()
		if mtime.After(activeCutoff) {
			results = append(results, DiscoveredSession{Path: p, Freshness: FreshActive})
		} else if mtime.After(restingCutoff) {
			results = append(results, DiscoveredSession{Path: p, Freshness: FreshResting})
		}
		// older than restingWindow → skip
	}
	return results
}
