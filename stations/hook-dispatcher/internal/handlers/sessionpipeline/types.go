// Package sessionpipeline — Go port of SessionPipelineClient orchestration.
//
// Five stages are run sequentially for a SessionEnd event:
//
//	0. pre-filter  — skip trivial / empty sessions           (Go)
//	1. redact      — scrub sensitive data from transcript    (Go)
//	2. extract     — LLM knowledge extraction (fire-and-forget Python)
//	3. archive     — session-archiver scan + score           (spawn CLI)
//	4. reflect     — JSONL quality scoring                   (Go)
//	5. log         — POST summary to hook-observatory        (Go)
//
// Stages 2 and 3 remain Python subprocesses because they invoke external
// tools (LLM, uv-managed archiver CLI) — porting would buy nothing. Every
// other stage runs entirely in-process.
package sessionpipeline

// StageResult mirrors SessionPipelineClient.StageResult.
type StageResult struct {
	Name       string         `json:"name"`
	Success    bool           `json:"success"`
	DurationMs int64          `json:"duration_ms"`
	Details    map[string]any `json:"details,omitempty"`
	Error      string         `json:"error,omitempty"`
}

// PipelineResult mirrors SessionPipelineClient.PipelineResult.
type PipelineResult struct {
	SessionID       string         `json:"session_id"`
	TranscriptPath  string         `json:"transcript_path,omitempty"`
	Stages          []StageResult  `json:"stages"`
	TotalDurationMs int64          `json:"total_duration_ms"`
}
