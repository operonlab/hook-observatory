// Package spool reads hook event JSONL from the observatory spool directory.
//
// Spool file layout (managed by internal/handlers/observability.go):
//
//	~/.hook-observatory/spool/
//	    events.jsonl                          # current append-only sink
//	    events-<ts>.processing                # rolled files mid-drain
//	    cursor.json                           # drainer progress
//
// JSONL record shape:
//
//	{"event_type":"SessionEnd","ts":"2026-05-13T13:00:11.000Z","data":{...}}
//
// This package only reads — writing remains in internal/handlers/observability.go
// so the dispatcher hot path stays single-purpose.
package spool

import (
	"bufio"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"time"
)

// Event is the in-memory shape after parsing a JSONL line.
// data is kept as RawMessage so callers can decode only what they need
// (most stats only touch a few keys like session_id / tool_name).
type Event struct {
	EventType string          `json:"event_type"`
	TS        time.Time       `json:"ts"`
	Data      json.RawMessage `json:"data"`
}

// SessionID extracts data.session_id if present. Empty string on miss.
func (e Event) SessionID() string { return strField(e.Data, "session_id") }

// ToolName extracts data.tool_name if present.
func (e Event) ToolName() string { return strField(e.Data, "tool_name") }

// HookEventName extracts data.hook_event_name if present.
func (e Event) HookEventName() string { return strField(e.Data, "hook_event_name") }

// DefaultSpoolDir resolves the canonical spool dir, honouring HOOK_OBS_SPOOL_DIR
// (used by tests) and falling back to ~/.hook-observatory/spool.
func DefaultSpoolDir() string {
	if v := os.Getenv("HOOK_OBS_SPOOL_DIR"); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ".hook-observatory/spool"
	}
	return filepath.Join(home, ".hook-observatory", "spool")
}

// Read scans the spool directory and returns all events ordered by TS asc.
// Files included: events.jsonl + events-*.processing (mid-drain files).
// Malformed lines are silently skipped — drainer is the consistency owner.
func Read(spoolDir string) ([]Event, error) {
	files, err := candidateFiles(spoolDir)
	if err != nil {
		return nil, err
	}
	var out []Event
	for _, f := range files {
		evs, err := readFile(f)
		if err != nil {
			// One unreadable file shouldn't poison the whole stats endpoint.
			continue
		}
		out = append(out, evs...)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].TS.Before(out[j].TS) })
	return out, nil
}

// candidateFiles returns the JSONL inputs in stable order.
func candidateFiles(dir string) ([]string, error) {
	main := filepath.Join(dir, "events.jsonl")
	procGlob := filepath.Join(dir, "events-*.processing")

	var files []string
	if _, err := os.Stat(main); err == nil {
		files = append(files, main)
	} else if !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	matches, err := filepath.Glob(procGlob)
	if err != nil {
		return nil, err
	}
	files = append(files, matches...)
	return files, nil
}

func readFile(path string) ([]Event, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return decode(f)
}

func decode(r io.Reader) ([]Event, error) {
	scanner := bufio.NewScanner(r)
	// Spool lines can be 100KB+ when payload contains transcripts; grow buf.
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)

	var out []Event
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var ev Event
		if err := json.Unmarshal(line, &ev); err != nil {
			continue
		}
		if ev.EventType == "" {
			continue
		}
		out = append(out, ev)
	}
	return out, scanner.Err()
}

// strField pulls a top-level string field from data without allocating
// a full map decode for every event (we touch 4-5 fields max).
func strField(data json.RawMessage, key string) string {
	if len(data) == 0 {
		return ""
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(data, &m); err != nil {
		return ""
	}
	raw, ok := m[key]
	if !ok {
		return ""
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		return ""
	}
	return s
}
