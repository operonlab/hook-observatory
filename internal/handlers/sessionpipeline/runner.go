package sessionpipeline

import (
	"bufio"
	"encoding/json"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	trivialSizeBytes int64 = 3_000
	minRealMsgsBytes int64 = 50_000
	scanLinesCap           = 100
)

// RunPipeline is the Go orchestrator for a SessionEnd session pipeline.
// Sequence: pre-filter → redact → extract → archive → reflect → log.
func RunPipeline(sessionID, transcriptPath string) PipelineResult {
	start := time.Now()
	result := PipelineResult{SessionID: sessionID}

	// Auto-detect transcript if not provided.
	if transcriptPath == "" {
		home, _ := os.UserHomeDir()
		if home != "" {
			transcriptPath = findTranscript(filepath.Join(home, ".claude", "projects"), sessionID)
		}
	}
	result.TranscriptPath = transcriptPath

	// ── Stage 0 — pre-filter ──
	if reason := shouldSkip(transcriptPath); reason != "" {
		result.Stages = append(result.Stages, StageResult{
			Name:    "pre-filter",
			Success: true,
			Details: map[string]any{"skipped": true, "reason": reason},
		})
		logResult := StageLog(&result)
		result.Stages = append(result.Stages, logResult)
		result.TotalDurationMs = time.Since(start).Milliseconds()
		return result
	}

	// ── Stage 1 — redact ──
	redact := StageRedact(sessionID, transcriptPath)
	result.Stages = append(result.Stages, redact)

	// ── Stage 2 — extract (skipped if redact failed, for safety) ──
	var extract StageResult
	if redact.Success {
		extract = StageExtract(sessionID, transcriptPath)
	} else {
		extract = StageResult{
			Name:    "extract",
			Success: false,
			Error:   "skipped: redact stage failed (safety policy)",
		}
	}
	result.Stages = append(result.Stages, extract)

	// ── Stage 3 — archive ──
	result.Stages = append(result.Stages, StageArchive(sessionID))

	// ── Stage 4 — reflect ──
	stagesOK, stagesFail := countStages(result.Stages)
	result.Stages = append(result.Stages, StageReflect(sessionID, transcriptPath, stagesOK, stagesFail))

	// ── Stage 5 — log ──
	result.Stages = append(result.Stages, StageLog(&result))

	result.TotalDurationMs = time.Since(start).Milliseconds()
	return result
}

// RunnerMain is the entry for `hook-observatory --session-pipeline-runner`.
// Reads `{"session_id", "transcript_path"}` JSON from argv[2] (safe for
// exec.Command without shell quoting) and runs the full pipeline.
func RunnerMain(payloadJSON string) {
	var payload struct {
		SessionID      string `json:"session_id"`
		TranscriptPath string `json:"transcript_path"`
	}
	if err := json.Unmarshal([]byte(payloadJSON), &payload); err != nil {
		return
	}
	if payload.SessionID == "" {
		return
	}
	_ = RunPipeline(payload.SessionID, payload.TranscriptPath)
}

// ---------------------------------------------------------------------------
// Helpers (duplicated from session_pipeline.go to keep the package self-contained)
// ---------------------------------------------------------------------------

// ShouldSkip is the exported trivial-session detector used by the handler's
// fast path (so we skip fork entirely for <3KB / empty sessions).
func ShouldSkip(transcriptPath string) string { return shouldSkip(transcriptPath) }

// FindTranscript exposes the projects-dir walker.
func FindTranscript(projectsDir, sessionID string) string {
	return findTranscript(projectsDir, sessionID)
}

func shouldSkip(transcriptPath string) string {
	if transcriptPath == "" {
		return ""
	}
	info, err := os.Stat(transcriptPath)
	if err != nil || info.IsDir() {
		return ""
	}
	size := info.Size()
	if size < trivialSizeBytes {
		return formatSkip("trivial: file_size=", size, "B < 3KB")
	}
	userMsgCount := scanRealUserMessages(transcriptPath)
	if userMsgCount == 0 && size < minRealMsgsBytes {
		return formatSkip("trivial: 0 user messages, size=", size, "B")
	}
	return ""
}

func scanRealUserMessages(path string) int {
	f, err := os.Open(path)
	if err != nil {
		return 0
	}
	defer f.Close()
	count := 0
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	lines := 0
	for scanner.Scan() {
		lines++
		if lines > scanLinesCap {
			break
		}
		var obj map[string]any
		if err := json.Unmarshal(scanner.Bytes(), &obj); err != nil {
			continue
		}
		if t, _ := obj["type"].(string); t != "user" {
			continue
		}
		if ut, _ := obj["userType"].(string); ut == "external" {
			continue
		}
		msg, _ := obj["message"].(map[string]any)
		if msg == nil {
			continue
		}
		content, ok := msg["content"].(string)
		if !ok {
			continue
		}
		if strings.HasPrefix(content, "<local-command-") ||
			strings.HasPrefix(content, "<command-name>") ||
			strings.HasPrefix(content, "<local-command-stdout>") {
			continue
		}
		if strings.TrimSpace(content) == "" {
			continue
		}
		count++
	}
	return count
}

func findTranscript(projectsDir, sessionID string) string {
	if projectsDir == "" || sessionID == "" {
		return ""
	}
	if _, err := os.Stat(projectsDir); err != nil {
		return ""
	}
	target := sessionID + ".jsonl"
	var found string
	_ = filepath.WalkDir(projectsDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if d.Name() == target {
			found = path
			return filepath.SkipAll
		}
		return nil
	})
	if found != "" {
		return found
	}
	if len(sessionID) < 8 {
		return ""
	}
	prefix := sessionID[:8]
	_ = filepath.WalkDir(projectsDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		name := d.Name()
		if strings.HasPrefix(name, prefix) && strings.HasSuffix(name, ".jsonl") {
			found = path
			return filepath.SkipAll
		}
		return nil
	})
	return found
}

func countStages(stages []StageResult) (ok, fail int) {
	for _, s := range stages {
		if s.Success {
			ok++
		} else {
			fail++
		}
	}
	return
}

func formatSkip(prefix string, size int64, suffix string) string {
	return prefix + int64ToString(size) + suffix
}

// int64ToString avoids pulling strconv just for one call site.
func int64ToString(n int64) string {
	if n == 0 {
		return "0"
	}
	var buf [20]byte
	i := len(buf)
	negative := false
	if n < 0 {
		negative = true
		n = -n
	}
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if negative {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}

// WriteTo is a small shim used by tests to capture runner output. Unused in
// production code; exists so we don't have an "unused import" block.
var _ = io.Discard
