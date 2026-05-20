package sessionpipeline

import (
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"time"

	portregistry "github.com/joneshong/hook-dispatcher/internal/portregistry"
)

const obsSecretDefault = "workshop-v2-dev-key"

// observatoryDefault points at the hook-observatory station via the
// cross-language port registry (hook-observatory = 10100).
var observatoryDefault = portregistry.URL("hook-observatory", "", 10100)

// StageLog posts the pipeline summary to hook-observatory. Mirrors _stage_log.
func StageLog(p *PipelineResult) StageResult {
	start := time.Now()
	r := StageResult{Name: "log", Success: true}

	obsURL := envOr("HOOK_OBS_URL", observatoryDefault)
	secret := envOr("HOOK_OBS_SECRET_KEY", obsSecretDefault)

	stagesSummary := make([]map[string]any, 0, len(p.Stages))
	for _, s := range p.Stages {
		stagesSummary = append(stagesSummary, map[string]any{
			"name":        s.Name,
			"success":     s.Success,
			"duration_ms": s.DurationMs,
		})
	}
	payload := map[string]any{
		"event_type": "SessionPipeline",
		"session_id": p.SessionID,
		"data": map[string]any{
			"transcript_path":   p.TranscriptPath,
			"stages":            stagesSummary,
			"total_duration_ms": p.TotalDurationMs,
		},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	req, err := http.NewRequest(http.MethodPost, strings.TrimRight(obsURL, "/")+"/api/events", bytes.NewReader(body))
	if err != nil {
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-local-key", secret)

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		// Parity with Python _stage_log: observatory-offline is NOT a
		// pipeline failure — we just fall back to local logging.  Keeping
		// Success=true prevents inflating pipeline_stages_fail on the
		// reflect counter when hook-observatory is intentionally down.
		r.Details = map[string]any{"fallback": "local_log"}
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	defer resp.Body.Close()
	r.Details = map[string]any{"status_code": resp.StatusCode}
	if resp.StatusCode >= 400 {
		// HTTP error from observatory IS observable — Python sets
		// stage.success = False and records the status code.
		r.Success = false
		r.Error = "observatory returned " + http.StatusText(resp.StatusCode)
	}
	r.DurationMs = time.Since(start).Milliseconds()
	return r
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
