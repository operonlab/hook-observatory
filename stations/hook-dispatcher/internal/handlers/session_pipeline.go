// Package handlers — session_pipeline.go
//
// SessionEnd handler. Pre-filter stays in the hook-dispatcher process so
// trivial sessions never pay the fork cost; everything else runs as a
// detached `hook-dispatcher --session-pipeline-runner <json>` child so the
// parent hook-dispatcher (a short-lived process) can exit immediately.
//
// The runner itself is fully Go: pre-filter, redact, extract, archive,
// reflect, log — see internal/handlers/sessionpipeline.
//
// Stages that still shell out to Python are the ones whose logic is an
// external tool rather than orchestrator code:
//
//	Stage 2 extract — spawns extract_async.py (LLM extraction)
//	Stage 3 archive — spawns `uv run session-archiver scan --json` CLI
//
// Those spawns happen inside Go; no Python orchestrator survives.
package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
	"github.com/joneshong/hook-dispatcher/internal/handlers/sessionpipeline"
)

func init() {
	core.Register("SessionEnd", core.Entry{
		Matcher:    "",
		Handler:    sessionPipelineHandle,
		Critical:   false,
		ModuleName: "session_pipeline",
	})
}

const (
	sessionPipelineObservatoryDefault = "http://127.0.0.1:10100"
	sessionPipelineObsSecretDefault   = "workshop-v2-dev-key"
)

func sessionPipelineHandle(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	var data map[string]any
	if strings.TrimSpace(rawInput) != "" {
		_ = json.Unmarshal([]byte(rawInput), &data)
	}
	if data == nil {
		data = map[string]any{}
	}

	sessionID, _ := data["session_id"].(string)
	if sessionID == "" {
		return core.Allow()
	}
	transcriptPath, _ := data["transcript_path"].(string)

	// Auto-detect transcript before forking so the trivial-skip fast path
	// stays in the hook-dispatcher process.
	if transcriptPath == "" {
		if home, err := os.UserHomeDir(); err == nil {
			if found := sessionpipeline.FindTranscript(filepath.Join(home, ".claude", "projects"), sessionID); found != "" {
				transcriptPath = found
			}
		}
	}

	// ── Stage 0 — pre-filter (Go, in-process) ──
	pipelineStart := time.Now()
	if skipReason := sessionpipeline.ShouldSkip(transcriptPath); skipReason != "" {
		stages := []map[string]any{
			{
				"name":        "pre-filter",
				"success":     true,
				"duration_ms": 0,
				"skipped":     true,
				"reason":      skipReason,
			},
		}
		go sessionPipelineLogSummary(sessionID, transcriptPath, stages, pipelineStart)
		return core.Allow()
	}

	// ── Non-trivial session → detach a Go runner and return immediately. ──
	payload, err := json.Marshal(map[string]string{
		"session_id":      sessionID,
		"transcript_path": transcriptPath,
	})
	if err != nil {
		return core.Allow()
	}

	self, err := os.Executable()
	if err != nil {
		return core.Allow()
	}
	if resolved, err := filepath.EvalSymlinks(self); err == nil {
		self = resolved
	}

	cmd := exec.Command(self, "--session-pipeline-runner", string(payload))
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		fmt.Fprintf(os.Stderr, "[session-pipeline] spawn runner failed: %v\n", err)
		return core.Allow()
	}
	_ = cmd.Process.Release()
	return core.Allow()
}

// sessionPipelineLogSummary posts a skip summary directly — used only on the
// trivial-skip path so the pre-filter decision is still observable.
func sessionPipelineLogSummary(sessionID, transcriptPath string, stages []map[string]any, start time.Time) {
	obsURL := os.Getenv("HOOK_OBS_URL")
	if obsURL == "" {
		obsURL = sessionPipelineObservatoryDefault
	}
	secret := os.Getenv("HOOK_OBS_SECRET_KEY")
	if secret == "" {
		secret = sessionPipelineObsSecretDefault
	}

	stagesSummary := make([]map[string]any, 0, len(stages))
	for _, s := range stages {
		stagesSummary = append(stagesSummary, map[string]any{
			"name":        s["name"],
			"success":     s["success"],
			"duration_ms": s["duration_ms"],
		})
	}
	payload := map[string]any{
		"event_type": "SessionPipeline",
		"session_id": sessionID,
		"data": map[string]any{
			"transcript_path":   transcriptPath,
			"stages":            stagesSummary,
			"total_duration_ms": int(time.Since(start).Milliseconds()),
		},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return
	}

	req, err := http.NewRequest(http.MethodPost, strings.TrimRight(obsURL, "/")+"/api/events", bytes.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-local-key", secret)

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return
	}
	_ = resp.Body.Close()
}
