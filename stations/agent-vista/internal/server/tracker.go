// Package server — AgentTracker maintains agent state derived from parsed events.
package server

import (
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/joneshong/agent-vista/internal/protocol"
)

const maxEventBuffer = 500

// EventEntry holds a sequenced event for REST polling.
type EventEntry struct {
	Seq      uint64               `json:"seq"`
	Event    protocol.AgentEvent  `json:"event"`
	NewAgent *protocol.AgentState `json:"new_agent,omitempty"`
}

// AgentTracker maintains a map of agent states, updated by incoming AgentEvents.
// Thread-safe for concurrent reads and writes.
// When a RedisStore is attached, state changes are persisted to Redis.
type AgentTracker struct {
	mu     sync.RWMutex
	agents map[string]*protocol.AgentState

	eventBuf []EventEntry
	nextSeq  uint64

	totalEvents atomic.Int64

	redis *RedisStore // optional; nil = in-memory only
}

// NewAgentTracker creates a new tracker with an empty agent map.
func NewAgentTracker() *AgentTracker {
	return &AgentTracker{
		agents:   make(map[string]*protocol.AgentState),
		eventBuf: make([]EventEntry, 0, maxEventBuffer),
	}
}

// SetRedis attaches a Redis store for state persistence.
// If agents exist in Redis, they are loaded into memory.
func (t *AgentTracker) SetRedis(r *RedisStore) {
	t.redis = r
	if r == nil {
		return
	}

	// Load persisted agents into memory
	agents, err := r.LoadAll()
	if err != nil {
		fmt.Printf("[tracker] warning: failed to load agents from Redis: %v\n", err)
		return
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	for i := range agents {
		a := agents[i]
		// Skip agents that went offline (stale data)
		if a.Status == protocol.StatusOffline {
			r.RemoveAgent(a.ID)
			continue
		}
		t.agents[a.ID] = &a
	}

	// Restore sequence counter from Redis
	if seq := r.LoadSeq(); seq > 0 {
		t.nextSeq = seq + 1
	}
}

// HandleEvent processes an AgentEvent and updates the corresponding agent state.
// Returns a copy of the newly created AgentState when a new agent is auto-created,
// or nil if the agent already existed.
func (t *AgentTracker) HandleEvent(evt protocol.AgentEvent) *protocol.AgentState {
	t.totalEvents.Add(1)

	t.mu.Lock()
	defer t.mu.Unlock()

	id := evt.AgentID
	if id == "" {
		// Fallback: derive agent ID from CLI type + session
		id = fmt.Sprintf("%s-%s", evt.CLIType, evt.SessionID)
	}

	agent, exists := t.agents[id]
	isNew := false
	if !exists {
		// Auto-create agent on first event or explicit session_start
		agent = &protocol.AgentState{
			ID:          id,
			CLIType:     evt.CLIType,
			SessionID:   evt.SessionID,
			DisplayName: displayName(evt.CLIType, evt.SessionID),
			Status:      protocol.StatusActive,
			Animation:   protocol.AnimIdle,
			LastActive:  time.Now().UnixMilli(),
		}
		t.agents[id] = agent
		isNew = true
	}

	// Update timestamp
	agent.LastActive = time.Now().UnixMilli()

	// Extract project directory from event metadata for process correlation
	if evt.Metadata != nil {
		if pd, ok := evt.Metadata["project_dir"]; ok {
			if pdStr, ok := pd.(string); ok && pdStr != "" {
				agent.ProjectDir = pdStr
			}
		}
	}

	// Accumulate tokens
	if evt.Tokens != nil {
		agent.TokensTotal += evt.Tokens.Total
	}

	// Map event type to status + animation
	switch evt.EventType {
	case protocol.EventSessionStart:
		agent.Status = protocol.StatusActive
		agent.Animation = protocol.AnimIdle
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventSessionEnd:
		agent.Status = protocol.StatusOffline
		agent.Animation = protocol.AnimIdle
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventThinking:
		agent.Status = protocol.StatusThinking
		agent.Animation = protocol.AnimThink
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventMessage:
		agent.Status = protocol.StatusActive
		agent.Animation = protocol.AnimType
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventIdle:
		agent.Status = protocol.StatusIdle
		agent.Animation = protocol.AnimIdle
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventWaiting:
		agent.Status = protocol.StatusWaiting
		agent.Animation = protocol.AnimWait
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventToolStart:
		agent.CurrentTool = evt.ToolName
		agent.ToolDetail = evt.ToolInput
		if isWriteTool(evt.ToolName) {
			agent.Status = protocol.StatusTyping
			agent.Animation = protocol.AnimType
		} else {
			agent.Status = protocol.StatusReading
			agent.Animation = protocol.AnimThink
		}

	case protocol.EventToolDone:
		agent.Status = protocol.StatusActive
		agent.Animation = protocol.AnimIdle
		agent.CurrentTool = ""
		agent.ToolDetail = ""

	case protocol.EventSubAgentStart:
		// Sub-agent events don't change the parent's primary status
		// but we note the activity
		agent.Status = protocol.StatusActive
		agent.Animation = protocol.AnimType

	case protocol.EventSubAgentEnd:
		agent.Status = protocol.StatusActive
		agent.Animation = protocol.AnimIdle
	}

	// Buffer event for REST polling
	entry := EventEntry{
		Seq:   t.nextSeq,
		Event: evt,
	}
	if isNew {
		agentCopy := *agent
		entry.NewAgent = &agentCopy
	}
	t.eventBuf = append(t.eventBuf, entry)
	if len(t.eventBuf) > maxEventBuffer {
		t.eventBuf = t.eventBuf[len(t.eventBuf)-maxEventBuffer:]
	}
	t.nextSeq++

	// Persist to Redis (non-blocking — errors logged but not propagated)
	if t.redis != nil {
		if evt.EventType == protocol.EventSessionEnd {
			t.redis.RemoveAgent(id)
		} else {
			agentCopy := *agent
			t.redis.SaveAgent(&agentCopy)
		}
		t.redis.SaveSeq(t.nextSeq - 1)
	}

	if isNew {
		copy := *agent
		return &copy
	}
	return nil
}

// Agents returns a snapshot of all tracked agent states.
func (t *AgentTracker) Agents() []protocol.AgentState {
	t.mu.RLock()
	defer t.mu.RUnlock()

	result := make([]protocol.AgentState, 0, len(t.agents))
	for _, a := range t.agents {
		result = append(result, *a)
	}
	return result
}

// ActiveSessionCount returns the number of agents that are not offline.
func (t *AgentTracker) ActiveSessionCount() int {
	t.mu.RLock()
	defer t.mu.RUnlock()

	count := 0
	for _, a := range t.agents {
		if a.Status != protocol.StatusOffline {
			count++
		}
	}
	return count
}

// TotalEvents returns the total number of events processed.
func (t *AgentTracker) TotalEvents() int64 {
	return t.totalEvents.Load()
}

// LatestSeq returns the sequence number of the most recent buffered event.
// Returns 0 if no events have been buffered yet.
func (t *AgentTracker) LatestSeq() uint64 {
	t.mu.RLock()
	defer t.mu.RUnlock()
	if t.nextSeq == 0 {
		return 0
	}
	return t.nextSeq - 1
}

// EventsSince returns all buffered events with Seq > afterSeq.
// Returns an empty slice (never nil) when there are no new events.
func (t *AgentTracker) EventsSince(afterSeq uint64) []EventEntry {
	t.mu.RLock()
	defer t.mu.RUnlock()

	var result []EventEntry
	for _, e := range t.eventBuf {
		if e.Seq > afterSeq {
			result = append(result, e)
		}
	}
	if result == nil {
		result = []EventEntry{}
	}
	return result
}

// isWriteTool returns true for tools that produce output (Write, Edit, Bash).
func isWriteTool(toolName string) bool {
	lower := strings.ToLower(toolName)
	switch lower {
	case "write", "edit", "bash":
		return true
	}
	return false
}

// displayName generates a human-readable name for an agent.
// Uses last 4 chars of session ID (random portion of UUID v7) to avoid
// collisions from shared timestamp prefixes.
func displayName(cli protocol.CLIType, sessionID string) string {
	short := sessionID
	if len(short) > 4 {
		short = short[len(short)-4:]
	}
	return fmt.Sprintf("%s-%s", cli, short)
}

// processRestingMs is the threshold for marking an agent as resting when its
// CLI process is still alive but the session transcript hasn't updated.
const processRestingMs = 3 * 60 * 1000 // 3 minutes

// ReconcileProcesses cross-references running CLI processes with tracked agents.
//
// Two lifecycle transitions:
//   - Process alive + session stale > 3 min → resting (go to rest room)
//   - Process dead → offline immediately (walk to exit or fade out)
//
// procs must be non-nil; nil means "scan failed" and reconciliation is skipped.
// An empty slice means "scan OK, no CLI processes running" — agents will be offlined.
// Returns IDs of agents that went offline.
func (t *AgentTracker) ReconcileProcesses(procs []protocol.ProcessInfo) []string {
	if procs == nil {
		return nil // no scan data — don't touch anything
	}

	now := time.Now()
	t.mu.Lock()
	defer t.mu.Unlock()

	var offlined []string
	for id, a := range t.agents {
		if a.Status == protocol.StatusOffline {
			continue
		}

		elapsed := now.UnixMilli() - a.LastActive

		// Grace period: don't touch agents that appeared very recently
		// (process might still be starting up or monitor hasn't seen it yet).
		if elapsed < 15_000 {
			continue
		}

		if hasMatchingProcess(a, procs) {
			// Process alive — check if session is stale → resting
			if elapsed > processRestingMs && a.Status != protocol.StatusResting {
				a.Status = protocol.StatusResting
				a.Animation = protocol.AnimIdle
				a.CurrentTool = ""
				a.ToolDetail = ""

				t.eventBuf = append(t.eventBuf, EventEntry{
					Seq: t.nextSeq,
					Event: protocol.AgentEvent{
						CLIType:   a.CLIType,
						SessionID: a.SessionID,
						AgentID:   id,
						Timestamp: now,
						EventType: protocol.EventProcessResting,
					},
				})
				t.nextSeq++

				if t.redis != nil {
					agentCopy := *a
					t.redis.SaveAgent(&agentCopy)
				}
			}
			continue
		}

		// No matching process — mark offline
		a.Status = protocol.StatusOffline
		a.Animation = protocol.AnimIdle
		a.CurrentTool = ""
		a.ToolDetail = ""
		offlined = append(offlined, id)

		t.eventBuf = append(t.eventBuf, EventEntry{
			Seq: t.nextSeq,
			Event: protocol.AgentEvent{
				CLIType:   a.CLIType,
				SessionID: a.SessionID,
				AgentID:   id,
				Timestamp: now,
				EventType: protocol.EventSessionEnd,
			},
		})
		t.nextSeq++

		if t.redis != nil {
			t.redis.RemoveAgent(id)
		}
	}
	return offlined
}

// hasMatchingProcess checks if any running process matches the given agent.
// Matching: same CLIType AND (ProjectDir/CWD prefix match, or either is empty).
func hasMatchingProcess(agent *protocol.AgentState, procs []protocol.ProcessInfo) bool {
	for _, p := range procs {
		if p.CLIType != agent.CLIType {
			continue
		}
		// If either side lacks directory info, match by CLI type alone
		if agent.ProjectDir == "" || p.CWD == "" {
			return true
		}
		// Prefix match in both directions (CWD might be parent or child of ProjectDir)
		if strings.HasPrefix(p.CWD, agent.ProjectDir) || strings.HasPrefix(agent.ProjectDir, p.CWD) {
			return true
		}
	}
	return false
}

// SweepStale checks all agents and marks them as resting or offline
// based on time since last activity. Returns IDs of agents that went offline.
func (t *AgentTracker) SweepStale(activeMs, restingMs int64) []string {
	now := time.Now().UnixMilli()

	t.mu.Lock()
	defer t.mu.Unlock()

	var offlined []string
	for id, a := range t.agents {
		if a.Status == protocol.StatusOffline {
			continue
		}
		elapsed := now - a.LastActive
		if elapsed > restingMs {
			a.Status = protocol.StatusOffline
			a.Animation = protocol.AnimIdle
			offlined = append(offlined, id)
			offlineEvt := protocol.AgentEvent{
				CLIType:   a.CLIType,
				SessionID: a.SessionID,
				AgentID:   id,
				Timestamp: time.Now(),
				EventType: protocol.EventSessionEnd,
			}
			t.eventBuf = append(t.eventBuf, EventEntry{
				Seq:   t.nextSeq,
				Event: offlineEvt,
			})
			t.nextSeq++
			// Remove from Redis
			if t.redis != nil {
				t.redis.RemoveAgent(id)
			}
		} else if elapsed > activeMs && a.Status != protocol.StatusResting {
			a.Status = protocol.StatusResting
			a.Animation = protocol.AnimIdle
			a.CurrentTool = ""
			a.ToolDetail = ""
			// Update resting status in Redis
			if t.redis != nil {
				agentCopy := *a
				t.redis.SaveAgent(&agentCopy)
			}
		}
	}
	return offlined
}
