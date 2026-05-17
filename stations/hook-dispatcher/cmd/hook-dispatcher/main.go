// hook-dispatcher: Go drop-in replacement for ~/.claude/hooks/dispatcher.py.
//
// Reads event_type from argv[1] and JSON payload from stdin, delegates to
// internal/core.Dispatch, writes the response to stdout.
//
// Contract (must match Python version byte-for-byte):
//   - Always exit 0
//   - Always output valid JSON (or passthrough text for UserPromptSubmit)
//   - Fail-open: any panic or error returns "{}"
package main

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"

	workshoplog "github.com/joneshong/workshop/libs/workshop-log"

	"github.com/joneshong/hook-dispatcher/internal/core"

	// Handler packages self-register via init().
	_ "github.com/joneshong/hook-dispatcher/internal/handlers"

	"github.com/joneshong/hook-dispatcher/internal/handlers/sessionpipeline"
	"github.com/joneshong/hook-dispatcher/internal/handlers/voicenotify"
)

// gitSHA is injected at build time via -ldflags.
var gitSHA = "dev"

// pythonFallbackDisable env var lets ops force Go-only path.
const pythonFallbackDisableEnv = "HOOK_DISPATCHER_NO_FALLBACK"

func main() {
	_ = workshoplog.Init("hook-dispatcher")

	// Sub-modes: self-exec for detached background workers.
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "--tts-consumer":
			voicenotify.ConsumerMain()
			return
		case "--tts-checker":
			ident := ""
			if len(os.Args) > 2 {
				ident = os.Args[2]
			}
			voicenotify.CheckerMain(ident)
			return
		case "--session-pipeline-runner":
			payload := ""
			if len(os.Args) > 2 {
				payload = os.Args[2]
			}
			sessionpipeline.RunnerMain(payload)
			return
		}
	}

	// Buffer raw stdin so we can replay it to Python on fallback.
	raw, readErr := io.ReadAll(os.Stdin)
	if readErr != nil {
		os.Stdout.Write([]byte("{}\n"))
		return
	}

	eventType := ""
	if len(os.Args) > 1 {
		eventType = os.Args[1]
	}

	// Outer recovery: on any uncaught panic, try Python fallback (unless disabled).
	defer func() {
		if r := recover(); r != nil {
			if !pythonFallback(eventType, raw) {
				os.Stdout.Write([]byte("{}\n"))
			}
		}
	}()

	output := core.Dispatch(eventType, string(raw))
	if output != "" {
		os.Stdout.Write([]byte(output))
		if output[len(output)-1] != '\n' {
			os.Stdout.Write([]byte("\n"))
		}
	}
}

// pythonFallback execs the legacy Python dispatcher with the same event_type
// and stdin. Returns true on success (output already written to stdout).
// Called only from the panic path to preserve parity when Go misbehaves.
func pythonFallback(eventType string, raw []byte) bool {
	if os.Getenv(pythonFallbackDisableEnv) == "1" {
		return false
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return false
	}
	pyDisp := filepath.Join(home, ".claude", "hooks", "dispatcher.py")
	if _, err := os.Stat(pyDisp); err != nil {
		return false
	}
	pyBin := filepath.Join(home, ".local", "bin", "python3")
	if _, err := os.Stat(pyBin); err != nil {
		pyBin = "python3"
	}

	cmd := exec.Command(pyBin, pyDisp, eventType)
	cmd.Stdin = bytes.NewReader(raw)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return false
	}
	return true
}
