// Package stats aggregates spool events into the views surfaced by the MCP
// server. All output is pre-formatted Markdown so MCP clients (Claude Code et
// al.) can render it directly without secondary parsing.
//
// Design choices vs the Python v0.1.0 implementation:
//
//   - DB-free: we read JSONL on demand instead of queueing INSERTs into
//     PostgreSQL/SQLite. v0.2.0 dropped the drainer service, so the spool IS
//     the source of truth. Re-scanning ~50k events takes <100ms on M-series.
//   - Streaming: we walk the spool once per call and fold into in-memory
//     counters. No goroutine for now — single-pass is faster than fan-out at
//     this dataset size (locality > parallelism).
//   - Typed: HookEvent struct + sort.Slice replace Python's dict-of-dicts.
package stats

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/spool"
)

// EventFilter narrows hook_obs_events queries.
type EventFilter struct {
	EventType string
	SessionID string
	ToolName  string
	Limit     int // 0 = default 20
}

// Summary captures total counts and the by-event distribution for
// hook_obs_stats.
type Summary struct {
	Total          int
	Today          int
	UniqueSessions int
	ByEventType    map[string]int // populated only when IncludeByEvent=true
}

// Stats reads the spool and aggregates counts.
// If includeByEvent is true, the ByEventType map is populated.
func Stats(spoolDir string, includeByEvent bool) (Summary, error) {
	events, err := spool.Read(spoolDir)
	if err != nil {
		return Summary{}, err
	}
	now := time.Now().UTC()
	yyyymmdd := now.Format("2006-01-02")

	sum := Summary{}
	sessions := make(map[string]struct{}, 128)
	if includeByEvent {
		sum.ByEventType = make(map[string]int, 16)
	}

	for _, ev := range events {
		sum.Total++
		if ev.TS.UTC().Format("2006-01-02") == yyyymmdd {
			sum.Today++
		}
		if sid := ev.SessionID(); sid != "" {
			sessions[sid] = struct{}{}
		}
		if includeByEvent {
			sum.ByEventType[ev.EventType]++
		}
	}
	sum.UniqueSessions = len(sessions)
	return sum, nil
}

// Events returns the most recent events matching filter, newest first.
// Output is bounded by filter.Limit (clamped to [1, 500], default 20).
func Events(spoolDir string, filter EventFilter) ([]spool.Event, error) {
	events, err := spool.Read(spoolDir)
	if err != nil {
		return nil, err
	}
	limit := filter.Limit
	if limit <= 0 {
		limit = 20
	}
	if limit > 500 {
		limit = 500
	}

	// Walk newest-first; collect up to limit.
	out := make([]spool.Event, 0, limit)
	for i := len(events) - 1; i >= 0 && len(out) < limit; i-- {
		ev := events[i]
		if filter.EventType != "" && ev.EventType != filter.EventType {
			continue
		}
		if filter.SessionID != "" && ev.SessionID() != filter.SessionID {
			continue
		}
		if filter.ToolName != "" && ev.ToolName() != filter.ToolName {
			continue
		}
		out = append(out, ev)
	}
	return out, nil
}

// ToolRank is one entry in the hook_obs_tools ranking.
type ToolRank struct {
	ToolName string
	Count    int
}

// Tools returns the top-N tool usage ranking, descending by count.
func Tools(spoolDir string, limit int) ([]ToolRank, error) {
	if limit <= 0 {
		limit = 20
	}
	events, err := spool.Read(spoolDir)
	if err != nil {
		return nil, err
	}
	counts := make(map[string]int, 32)
	for _, ev := range events {
		if name := ev.ToolName(); name != "" {
			counts[name]++
		}
	}
	out := make([]ToolRank, 0, len(counts))
	for k, v := range counts {
		out = append(out, ToolRank{ToolName: k, Count: v})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Count > out[j].Count })
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

// ────────────────────────────────────────────────────────────────────────
// Markdown renderers — kept here so MCP server can call one function per tool.
// ────────────────────────────────────────────────────────────────────────

// RenderStats turns Summary into a Markdown overview for hook_obs_stats.
func RenderStats(s Summary) string {
	var b strings.Builder
	fmt.Fprintf(&b, "# Hook Observatory — Stats\n\n")
	fmt.Fprintf(&b, "- **Total events:** %d\n", s.Total)
	fmt.Fprintf(&b, "- **Today:** %d\n", s.Today)
	fmt.Fprintf(&b, "- **Unique sessions:** %d\n", s.UniqueSessions)
	if len(s.ByEventType) > 0 {
		b.WriteString("\n## By event type\n\n")
		type kv struct {
			k string
			v int
		}
		pairs := make([]kv, 0, len(s.ByEventType))
		for k, v := range s.ByEventType {
			pairs = append(pairs, kv{k, v})
		}
		sort.Slice(pairs, func(i, j int) bool { return pairs[i].v > pairs[j].v })
		b.WriteString("| Event type | Count |\n|---|---:|\n")
		for _, p := range pairs {
			fmt.Fprintf(&b, "| %s | %d |\n", p.k, p.v)
		}
	}
	return b.String()
}

// RenderEvents formats an event list for hook_obs_events.
func RenderEvents(events []spool.Event, filter EventFilter) string {
	var b strings.Builder
	fmt.Fprintf(&b, "# Hook Observatory — Events\n\n")
	if filter.EventType != "" || filter.SessionID != "" || filter.ToolName != "" {
		b.WriteString("Filter:")
		if filter.EventType != "" {
			fmt.Fprintf(&b, " event_type=`%s`", filter.EventType)
		}
		if filter.SessionID != "" {
			fmt.Fprintf(&b, " session_id=`%s`", filter.SessionID)
		}
		if filter.ToolName != "" {
			fmt.Fprintf(&b, " tool_name=`%s`", filter.ToolName)
		}
		b.WriteString("\n\n")
	}
	if len(events) == 0 {
		b.WriteString("_No matching events._\n")
		return b.String()
	}
	b.WriteString("| TS | Event | Session | Tool |\n|---|---|---|---|\n")
	for _, ev := range events {
		fmt.Fprintf(&b, "| %s | %s | %s | %s |\n",
			ev.TS.UTC().Format(time.RFC3339),
			ev.EventType,
			shortID(ev.SessionID()),
			ev.ToolName(),
		)
	}
	return b.String()
}

// RenderTools formats the tool ranking for hook_obs_tools.
func RenderTools(ranks []ToolRank) string {
	var b strings.Builder
	fmt.Fprintf(&b, "# Hook Observatory — Tool usage\n\n")
	if len(ranks) == 0 {
		b.WriteString("_No tool events recorded._\n")
		return b.String()
	}
	b.WriteString("| # | Tool | Count |\n|---:|---|---:|\n")
	for i, r := range ranks {
		fmt.Fprintf(&b, "| %d | %s | %d |\n", i+1, r.ToolName, r.Count)
	}
	return b.String()
}

func shortID(id string) string {
	if len(id) <= 8 {
		return id
	}
	return id[:8] + "…"
}
