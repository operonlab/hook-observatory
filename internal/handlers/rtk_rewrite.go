package handlers

import (
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Bash",
		Handler:    rtkRewriteHandle,
		Critical:   false,
		ModuleName: "rtk_rewrite",
	})
}

// rtkRewriteHandle is the Go port of handlers/rtk_rewrite.py.
//
// Delegates command rewriting to the `rtk rewrite` binary (Rust, <10ms).
// Returns an UpdatedInput if the command was rewritten, otherwise Allow.
func rtkRewriteHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Bash" {
		return core.Allow()
	}

	cmd, _ := toolInput["command"].(string)
	if cmd == "" || strings.HasPrefix(cmd, "rtk ") {
		return core.Allow()
	}

	rtkBin := core.Cfg().GetTool("rtk")
	if rtkBin == "" {
		return core.Allow()
	}

	result := core.RunCmd([]string{rtkBin, "rewrite", cmd}, "", 3*time.Second, "")
	if result == nil || result.ExitCode != 0 {
		return core.Allow()
	}

	rewritten := strings.TrimSpace(result.Stdout)
	if rewritten == "" || rewritten == cmd {
		return core.Allow()
	}

	return core.HookResult{UpdatedInput: map[string]any{"command": rewritten}}
}
