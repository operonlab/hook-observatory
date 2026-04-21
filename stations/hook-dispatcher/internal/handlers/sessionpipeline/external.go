package sessionpipeline

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

// StageExtract launches the memvault extract_async.py script as a detached
// subprocess, mirroring _stage_extract in session_pipeline.py. The script
// internally calls an LLM, so porting is out of scope for this handler.
func StageExtract(sessionID, transcriptPath string) StageResult {
	start := time.Now()
	r := StageResult{Name: "extract", Success: true}

	home, err := os.UserHomeDir()
	if err != nil {
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	script := filepath.Join(home, "workshop", "mcp", "memvault", "scripts", "extract_async.py")
	if _, err := os.Stat(script); err != nil {
		r.Success = false
		r.Error = fmt.Sprintf("extract script not found: %s", script)
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	python := filepath.Join(home, ".local", "bin", "python3")
	logDir := filepath.Join(home, ".claude", "data", "session-pipeline")
	_ = os.MkdirAll(logDir, 0o755)
	logFile := filepath.Join(logDir, "extract.log")

	logF, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		r.Success = false
		r.Error = fmt.Sprintf("open log: %v", err)
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	defer logF.Close()

	payload, _ := json.Marshal(map[string]any{
		"session_id":      sessionID,
		"transcript_path": transcriptPath,
	})

	cmd := exec.Command(python, script)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	cmd.Stdout = nil
	cmd.Stderr = logF
	if err := cmd.Start(); err != nil {
		_ = stdin.Close()
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	_, _ = stdin.Write(payload)
	_ = stdin.Close()
	// Detach fully — don't Wait(); parent will exit and PID 1 reaps it.
	_ = cmd.Process.Release()

	r.Details = map[string]any{
		"pid":  cmd.Process.Pid,
		"mode": "background",
		"log":  logFile,
	}
	r.DurationMs = time.Since(start).Milliseconds()
	return r
}

// StageArchive invokes the session-archiver CLI (`uv run session-archiver scan`)
// and parses the --json output. Mirrors _stage_archive. The CLI itself is a
// heavy uv-managed package; we do not port its logic.
func StageArchive(sessionID string) StageResult {
	start := time.Now()
	r := StageResult{Name: "archive", Success: true}

	home, err := os.UserHomeDir()
	if err != nil {
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	cliDir := filepath.Join(home, "workshop", "stations", "session-archiver")
	uv := "/opt/homebrew/bin/uv"

	cmd := exec.Command(uv, "run", "--directory", cliDir, "session-archiver", "scan",
		"--session-id", sessionID, "--json")
	out, err := cmd.Output()
	if err != nil {
		r.Success = false
		if ee, ok := err.(*exec.ExitError); ok {
			r.Error = fmt.Sprintf("exit %d: %s", ee.ExitCode(), string(ee.Stderr))
		} else {
			r.Error = err.Error()
		}
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	var scan map[string]any
	if err := json.Unmarshal(out, &scan); err != nil {
		// Not fatal — just log raw length
		r.Details = map[string]any{"raw_bytes": len(out)}
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	r.Details = map[string]any{
		"scanned":  scan["scanned"],
		"upserted": scan["upserted"],
	}
	r.DurationMs = time.Since(start).Milliseconds()
	return r
}
