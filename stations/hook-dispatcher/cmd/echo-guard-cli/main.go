// cmd/echo-guard-cli — Layer 3 E2E test wrapper (testing only, may be removed post-test)
//
// Usage:
//   echo-guard-cli detect   < input.txt   → exits 0 if echo, 1 if clean
//   echo-guard-cli strip    < input.txt   → prints stripped text to stdout
//
// This binary is intentionally NOT wired into the main dispatcher.
// It exists solely to enable CLI-level E2E testing of LooksLikeSystemEcho
// and StripSystemEchoes without requiring dispatcher.go wiring.

package main

import (
	"fmt"
	"io"
	"os"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: echo-guard-cli <detect|strip>")
		os.Exit(2)
	}

	input, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "read stdin: %v\n", err)
		os.Exit(2)
	}
	text := string(input)

	switch os.Args[1] {
	case "detect":
		if core.LooksLikeSystemEcho(text) {
			fmt.Println("echo")
			os.Exit(0)
		}
		fmt.Println("clean")
		os.Exit(1)

	case "strip":
		fmt.Print(core.StripSystemEchoes(text))
		os.Exit(0)

	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand: %s\n", os.Args[1])
		os.Exit(2)
	}
}
