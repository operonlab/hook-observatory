package handlers

import (
	"os"
	"os/exec"
	"path/filepath"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

// voice_notify.go — subprocess bridge to the Python voice_notify handler.
//
// The Python implementation is 839 LOC of Redis-backed debounce, PID-based
// subagent tracking, deferred TTS checker scripts, and AppleScript calls. A
// faithful Go port is a multi-day effort; for now we keep Python authoritative
// and fire it fire-and-forget from Go so TTS behavior survives Stage 3 cutover.

func init() {
	entry := core.Entry{
		Handler:    voiceNotifyBridge,
		ModuleName: "voice_notify",
	}
	core.Register("PreToolUse", core.Entry{
		Matcher:    "AskUserQuestion",
		Handler:    voiceNotifyBridge,
		ModuleName: "voice_notify",
	})
	core.Register("Stop", entry)
	core.Register("SubagentStart", entry)
	core.Register("SubagentStop", entry)
}

// voiceNotifyBridge spawns the Python runner in the background. Any failure is
// swallowed — voice alerts are non-blocking nice-to-haves, never safety gates.
func voiceNotifyBridge(_, _ string, _ map[string]any, raw string) core.HookResult {
	python := core.Cfg().GetTool("python")
	if python == "" {
		home, _ := os.UserHomeDir()
		python = filepath.Join(home, ".local", "bin", "python3")
	}
	home, _ := os.UserHomeDir()
	runner := filepath.Join(home, "workshop", "stations", "hook-observatory", "voice_notify_runner.py")
	if _, err := os.Stat(runner); err != nil {
		return core.Allow()
	}

	cmd := exec.Command(python, runner, currentEventType())
	// We still pipe stdin so voice_notify sees the raw payload. Write the
	// buffered raw string synchronously, then detach.
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return core.Allow()
	}
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		_ = stdin.Close()
		return core.Allow()
	}
	// Write+close stdin in a goroutine so Start returns immediately; reap proc
	// to avoid zombies.
	go func(c *exec.Cmd, pipe interface {
		Write([]byte) (int, error)
		Close() error
	}, data string) {
		_, _ = pipe.Write([]byte(data))
		_ = pipe.Close()
		_ = c.Wait()
	}(cmd, stdin, raw)

	return core.Allow()
}

// currentEventType returns os.Args[1] which is the event_type the dispatcher
// was launched with. Using a function here lets tests override via exec.
func currentEventType() string {
	if len(os.Args) > 1 {
		return os.Args[1]
	}
	return ""
}
