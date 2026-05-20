package clients

import (
	"fmt"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const ghTimeout = 10 * time.Second

// RunGH executes the `gh` CLI with the given args and returns stdout.
// Returns ("", err) on failure — callers should treat as fail-open.
func RunGH(args []string) (string, error) {
	all := append([]string{"gh"}, args...)
	r := core.RunCmd(all, "", ghTimeout, "")
	if r == nil {
		return "", fmt.Errorf("gh: command failed to start")
	}
	if r.ExitCode != 0 {
		stderr := strings.TrimSpace(r.Stderr)
		if stderr == "" {
			stderr = fmt.Sprintf("exit code %d", r.ExitCode)
		}
		return "", fmt.Errorf("gh: %s", stderr)
	}
	return strings.TrimSpace(r.Stdout), nil
}

// RunGHBackground runs a `gh` command fire-and-forget in the background.
func RunGHBackground(args []string) {
	all := append([]string{"gh"}, args...)
	_ = core.RunBackground(all, "")
}
