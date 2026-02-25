// Package watcher monitors transcript files for changes and emits parsed AgentEvents.
package watcher

import (
	"context"
	"io"
	"log"
	"os"
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/joneshong/agent-vista/internal/parser"
	"github.com/joneshong/agent-vista/internal/protocol"
)

// ParserFactory creates a new TranscriptParser instance.
// Each watched file gets its own parser instance to maintain independent state.
type ParserFactory func() parser.TranscriptParser

// trackedFile holds the state for a single watched transcript file.
type trackedFile struct {
	path   string
	parser parser.TranscriptParser
	offset int64
}

// Watcher monitors transcript files and emits parsed AgentEvents via a callback.
type Watcher struct {
	fsw       *fsnotify.Watcher
	files     map[string]*trackedFile
	mu        sync.RWMutex
	factories []ParserFactory
	onEvent   func(protocol.AgentEvent)
	done      chan struct{}
	verbose   bool
}

// New creates a new file watcher.
// onEvent is called for each parsed AgentEvent (must be thread-safe).
func New(onEvent func(protocol.AgentEvent), verbose bool) (*Watcher, error) {
	fsw, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}

	return &Watcher{
		fsw:     fsw,
		files:   make(map[string]*trackedFile),
		onEvent: onEvent,
		done:    make(chan struct{}),
		verbose: verbose,
	}, nil
}

// RegisterParserFactory adds a parser factory. When a new file is watched,
// each factory is tried via Detect() to find the matching parser.
func (w *Watcher) RegisterParserFactory(f ParserFactory) {
	w.factories = append(w.factories, f)
}

// WatchFile starts watching a specific transcript file.
// It performs an initial read of existing content, then watches for changes.
func (w *Watcher) WatchFile(path string) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if _, exists := w.files[path]; exists {
		return nil // already watching
	}

	// Find matching parser
	p := w.findParser(path)
	if p == nil {
		if w.verbose {
			log.Printf("[watcher] no parser matched for: %s", path)
		}
		return nil
	}

	tf := &trackedFile{
		path:   path,
		parser: p,
		offset: 0,
	}
	w.files[path] = tf

	// Initial read of existing content
	w.readNew(tf)

	// Add to fsnotify
	if err := w.fsw.Add(path); err != nil {
		delete(w.files, path)
		return err
	}

	if w.verbose {
		meta := p.SessionInfo()
		log.Printf("[watcher] watching: %s (cli=%s, session=%s)", path, meta.CLIType, meta.SessionID)
	}

	return nil
}

// UnwatchFile stops watching a file.
func (w *Watcher) UnwatchFile(path string) {
	w.mu.Lock()
	defer w.mu.Unlock()

	if _, exists := w.files[path]; exists {
		w.fsw.Remove(path)
		delete(w.files, path)
	}
}

// Start begins the event loop. Blocks until ctx is cancelled.
func (w *Watcher) Start(ctx context.Context) error {
	defer w.fsw.Close()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()

		case event, ok := <-w.fsw.Events:
			if !ok {
				return nil
			}
			if event.Has(fsnotify.Write) {
				w.handleWrite(event.Name)
			}

		case err, ok := <-w.fsw.Errors:
			if !ok {
				return nil
			}
			log.Printf("[watcher] fsnotify error: %v", err)
		}
	}
}

// Close stops watching all files.
func (w *Watcher) Close() {
	w.fsw.Close()
}

// WatchedFiles returns paths of all currently watched files.
func (w *Watcher) WatchedFiles() []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	paths := make([]string, 0, len(w.files))
	for p := range w.files {
		paths = append(paths, p)
	}
	return paths
}

// --- Internal ---

func (w *Watcher) findParser(path string) parser.TranscriptParser {
	for _, factory := range w.factories {
		p := factory()
		if p.Detect(path) {
			return p
		}
	}
	return nil
}

func (w *Watcher) handleWrite(path string) {
	w.mu.RLock()
	tf, exists := w.files[path]
	w.mu.RUnlock()

	if !exists {
		return
	}

	w.readNew(tf)
}

func (w *Watcher) readNew(tf *trackedFile) {
	f, err := os.Open(tf.path)
	if err != nil {
		if w.verbose {
			log.Printf("[watcher] open error %s: %v", tf.path, err)
		}
		return
	}
	defer f.Close()

	// Seek to last known offset
	if tf.offset > 0 {
		if _, err := f.Seek(tf.offset, io.SeekStart); err != nil {
			log.Printf("[watcher] seek error %s: %v", tf.path, err)
			return
		}
	}

	// Read new bytes
	newBytes, err := io.ReadAll(f)
	if err != nil {
		log.Printf("[watcher] read error %s: %v", tf.path, err)
		return
	}

	if len(newBytes) == 0 {
		return
	}

	// Update offset
	tf.offset += int64(len(newBytes))

	// Parse and emit events
	events, err := tf.parser.ParseIncremental(newBytes)
	if err != nil {
		log.Printf("[watcher] parse error %s: %v", tf.path, err)
		return
	}

	// Inject project dir from session metadata into events
	meta := tf.parser.SessionInfo()
	for i := range events {
		if meta.ProjectDir != "" {
			if events[i].Metadata == nil {
				events[i].Metadata = make(map[string]any)
			}
			if _, exists := events[i].Metadata["project_dir"]; !exists {
				events[i].Metadata["project_dir"] = meta.ProjectDir
			}
		}
		w.onEvent(events[i])
	}

	if w.verbose && len(events) > 0 {
		log.Printf("[watcher] %s: %d new events", tf.path, len(events))
	}
}
