// cmd/pre-compact-cli — Layer 3 E2E test wrapper (testing only, may be removed post-test)
//
// Usage:
//   echo '{"session_id":"x","trigger":"auto","cwd":"/tmp"}' | pre-compact-cli
//
// Reads a PreCompact event JSON from stdin, runs the handler via core.Dispatch,
// prints dispatcher JSON output to stdout, and exits 0.
// Exit 1 if stdin is unreadable or output is not JSON.
//
// This binary is intentionally NOT wired into the main dispatcher.

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/joneshong/hook-observatory/internal/core"
	"github.com/joneshong/hook-observatory/internal/handlers"
)

func main() {
	core.Reset()
	handlers.RegisterPreCompact()

	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "read stdin: %v\n", err)
		os.Exit(1)
	}

	result := core.Dispatch("PreCompact", string(raw))

	// Validate output is JSON before printing.
	var check map[string]any
	if err := json.Unmarshal([]byte(result), &check); err != nil {
		fmt.Fprintf(os.Stderr, "dispatcher returned non-JSON: %v\nraw=%s\n", err, result)
		os.Exit(1)
	}

	fmt.Print(result)
	os.Exit(0)
}
