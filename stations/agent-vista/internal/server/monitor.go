// Package server — ProcessMonitor collects resource usage of LLM CLI processes.
package server

import (
	"context"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/shirou/gopsutil/v3/process"

	"github.com/joneshong/agent-vista/internal/broker"
	"github.com/joneshong/agent-vista/internal/protocol"
)

// cliKeywords maps substrings in process names to CLIType.
var cliKeywords = []struct {
	keyword string
	cli     protocol.CLIType
}{
	{"claude", protocol.CLIClaude},
	{"codex", protocol.CLICodex},
	{"gemini", protocol.CLIGemini},
}

// cliCmdPatterns matches executable paths/names in cmdline strings.
// More specific than keyword matching to avoid false positives like ~/Claude/ paths.
var cliCmdPatterns = []struct {
	pattern string
	cli     protocol.CLIType
}{
	{"/claude ", protocol.CLIClaude},
	{"claude --", protocol.CLIClaude},
	{"/codex ", protocol.CLICodex},
	{"codex --", protocol.CLICodex},
	{"/codex-", protocol.CLICodex},
	{"/gemini ", protocol.CLIGemini},
	{"gemini --", protocol.CLIGemini},
	{"@google/gemini-cli", protocol.CLIGemini},
}

// ProcessMonitor periodically collects resource usage of LLM CLI processes.
type ProcessMonitor struct {
	broker         *broker.Broker
	interval       time.Duration
	verbose        bool
	latestSnapshot []protocol.ProcessInfo
	mu             sync.RWMutex
}

// NewProcessMonitor creates a new monitor that publishes WSResourceSnapshot
// to the broker at the given interval.
func NewProcessMonitor(b *broker.Broker, interval time.Duration, verbose bool) *ProcessMonitor {
	return &ProcessMonitor{
		broker:   b,
		interval: interval,
		verbose:  verbose,
	}
}

// Start runs the monitor loop in a goroutine-safe manner.
// It blocks until ctx is cancelled.
func (pm *ProcessMonitor) Start(ctx context.Context) {
	ticker := time.NewTicker(pm.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			procs := pm.CollectOnce()
			pm.mu.Lock()
			pm.latestSnapshot = procs
			pm.mu.Unlock()
			pm.broker.Publish(protocol.WSMessage{
				Type: protocol.WSTypeResourceSnapshot,
				ResourceSnapshot: &protocol.WSResourceSnapshot{
					Processes: procs,
				},
			})
		}
	}
}

// CollectOnce performs a single scan of all OS processes, returning info
// for CLI process trees. It first identifies root CLI processes (by name or
// cmdline), then walks child trees and aggregates resource usage per CLI type.
func (pm *ProcessMonitor) CollectOnce() []protocol.ProcessInfo {
	procs, err := process.Processes()
	if err != nil {
		if pm.verbose {
			log.Printf("[monitor] failed to list processes: %v", err)
		}
		return nil
	}

	// Phase 1: Build PID → process map and parent→children map
	pidMap := make(map[int32]*process.Process, len(procs))
	childMap := make(map[int32][]int32) // parent → children
	ppidMap := make(map[int32]int32)    // pid → parent pid

	for _, p := range procs {
		pidMap[p.Pid] = p
		ppid, err := p.Ppid()
		if err == nil && ppid > 0 {
			childMap[ppid] = append(childMap[ppid], p.Pid)
			ppidMap[p.Pid] = ppid
		}
	}

	// Phase 2: Identify root CLI processes
	type rootInfo struct {
		pid     int32
		cliType protocol.CLIType
	}
	var roots []rootInfo
	rootSet := make(map[int32]bool) // track which PIDs are already roots

	for _, p := range procs {
		// Match by process name first (fast path: e.g. "claude" binary)
		name, err := p.Name()
		if err != nil {
			continue
		}
		lower := strings.ToLower(name)
		if cliType, ok := matchCLI(lower); ok {
			roots = append(roots, rootInfo{p.Pid, cliType})
			rootSet[p.Pid] = true
			continue
		}

		// Match by cmdline patterns (for node-based CLIs)
		cmdline, err := p.Cmdline()
		if err != nil || cmdline == "" {
			continue
		}
		lowerCmd := strings.ToLower(cmdline)
		if cliType, ok := matchCmdline(lowerCmd); ok {
			// Only treat as root if no ancestor is already a root
			if !hasAncestorInSet(p.Pid, ppidMap, rootSet) {
				roots = append(roots, rootInfo{p.Pid, cliType})
				rootSet[p.Pid] = true
			}
		}
	}

	// Phase 3: For each root, BFS collect descendants and aggregate resources
	var result []protocol.ProcessInfo
	claimed := make(map[int32]bool) // avoid double-counting across trees

	for _, root := range roots {
		var totalCPU float64
		var totalRSS uint64
		var totalThreads int32
		count := 0

		queue := []int32{root.pid}
		for len(queue) > 0 {
			pid := queue[0]
			queue = queue[1:]
			if claimed[pid] {
				continue
			}
			claimed[pid] = true

			p, ok := pidMap[pid]
			if !ok {
				continue
			}
			count++

			if cpuPct, err := p.CPUPercent(); err == nil {
				totalCPU += cpuPct
			}
			if memInfo, err := p.MemoryInfo(); err == nil && memInfo != nil {
				totalRSS += memInfo.RSS
			}
			if threads, err := p.NumThreads(); err == nil {
				totalThreads += threads
			}

			for _, child := range childMap[pid] {
				queue = append(queue, child)
			}
		}

		result = append(result, protocol.ProcessInfo{
			PID:     root.pid,
			Name:    string(root.cliType),
			CLIType: root.cliType,
			CPU:     totalCPU,
			RSS:     totalRSS,
			Threads: totalThreads,
		})

		if pm.verbose {
			log.Printf("[monitor] %s (pid=%d, procs=%d): cpu=%.1f%%, rss=%d, threads=%d",
				root.cliType, root.pid, count, totalCPU, totalRSS, totalThreads)
		}
	}

	return result
}

// LatestSnapshot returns the most recent process info collected by the monitor.
func (pm *ProcessMonitor) LatestSnapshot() []protocol.ProcessInfo {
	pm.mu.RLock()
	defer pm.mu.RUnlock()
	out := make([]protocol.ProcessInfo, len(pm.latestSnapshot))
	copy(out, pm.latestSnapshot)
	return out
}

// matchCLI checks if a lowercase process name contains any known CLI keyword.
func matchCLI(lowerName string) (protocol.CLIType, bool) {
	for _, kw := range cliKeywords {
		if strings.Contains(lowerName, kw.keyword) {
			return kw.cli, true
		}
	}
	return "", false
}

// matchCmdline checks if a lowercase cmdline matches any known CLI executable pattern.
// More specific than matchCLI to avoid false positives (e.g., paths containing "Claude").
func matchCmdline(lowerCmd string) (protocol.CLIType, bool) {
	for _, pat := range cliCmdPatterns {
		if strings.Contains(lowerCmd, pat.pattern) {
			return pat.cli, true
		}
	}
	return "", false
}

// hasAncestorInSet checks if any ancestor of pid is in the given set.
func hasAncestorInSet(pid int32, ppidMap map[int32]int32, set map[int32]bool) bool {
	visited := make(map[int32]bool)
	cur := pid
	for {
		parent, ok := ppidMap[cur]
		if !ok || parent <= 1 || visited[parent] {
			return false
		}
		if set[parent] {
			return true
		}
		visited[parent] = true
		cur = parent
	}
}
