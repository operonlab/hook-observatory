package autocomplete

import (
	"os"
	"strings"
	"time"
)

const defaultMaxResults = 15

// Options configures the autocomplete Engine.
type Options struct {
	// ClaudeDir enables scanning of ~/.claude/{skills,commands,agents}.
	// Pass an empty string to disable; path completion is always enabled.
	// "~" is NOT expanded here — pass os.UserHomeDir() + "/.claude" explicitly,
	// or use ExpandClaudeDir() if you want automatic "~/.claude" expansion.
	ClaudeDir string

	// RefreshInterval controls how often the background scanner runs.
	// Zero defaults to 5 minutes.
	RefreshInterval time.Duration
}

// ExpandClaudeDir returns ~/.claude expanded to an absolute path.
// Returns empty string if home dir is unavailable.
func ExpandClaudeDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return home + "/.claude"
}

// Engine is the main autocomplete engine.
type Engine struct {
	cache *ResourceCache
}

// New creates an Engine with the provided options. A background scanner goroutine
// is started immediately if ClaudeDir is non-empty.
func New(opts Options) *Engine {
	var scanner *ClaudeDirScanner
	if opts.ClaudeDir != "" {
		scanner = NewClaudeDirScanner(opts.ClaudeDir)
	}
	return &Engine{
		cache: newResourceCache(scanner, opts.RefreshInterval),
	}
}

// Complete routes the query and returns up to defaultMaxResults suggestions.
//
// Routing rules (mirrors Python complete()):
//
//   - typeFilter == "path"              → path completion
//   - query starts with "/"            → slash items (skills + commands)
//   - typeFilter == "skill"/"command"  → slash items with type filter
//   - query starts with "@"            → at items (agents + mcp)
//   - query starts with "~" or "./"    → path completion
//   - "/" found anywhere in query      → path completion
//   - empty query                      → empty slice
func (e *Engine) Complete(query, typeFilter string) []Item {
	query = strings.TrimSpace(query)
	if query == "" {
		return nil
	}

	// Explicit path mode.
	if typeFilter == "path" {
		return completePath(query, defaultMaxResults)
	}

	// "/" trigger → skill or command items.
	if typeFilter == "skill" || typeFilter == "command" ||
		(typeFilter == "" && strings.HasPrefix(query, "/")) {

		search := strings.TrimLeft(query, "/")
		items := e.cache.slashItems()

		// Narrow by typeFilter when explicitly set.
		if typeFilter == "skill" || typeFilter == "command" {
			items = filterByType(items, typeFilter)
		}

		return rankAndFilter(items, search, defaultMaxResults)
	}

	// "@" trigger → agent or mcp items.
	if typeFilter == "at" || (typeFilter == "" && strings.HasPrefix(query, "@")) {
		search := strings.TrimLeft(query, "@")
		items := e.cache.atItems()
		return rankAndFilter(items, search, defaultMaxResults)
	}

	// Implicit path detection.
	if strings.HasPrefix(query, "~/") || strings.HasPrefix(query, "./") ||
		strings.Contains(query, "/") {
		return completePath(query, defaultMaxResults)
	}

	return nil
}

// Refresh forces an immediate re-scan and returns the updated Stats.
func (e *Engine) Refresh() Stats {
	return e.cache.forceRefresh()
}

// Stats returns the current cache statistics without triggering a scan.
func (e *Engine) Stats() Stats {
	return e.cache.snapshot()
}

// Close stops the background refresh goroutine. Call via defer after New().
func (e *Engine) Close() {
	e.cache.Close()
}

// filterByType returns only items whose Type matches t.
func filterByType(items []Item, t string) []Item {
	out := make([]Item, 0, len(items))
	for _, it := range items {
		if it.Type == t {
			out = append(out, it)
		}
	}
	return out
}
