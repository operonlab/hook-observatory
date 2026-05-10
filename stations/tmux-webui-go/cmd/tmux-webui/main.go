package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/operonlab/tmux-webui/internal/buildinfo"
)

func main() {
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()

	if *showVersion {
		fmt.Println(buildinfo.String())
		return
	}

	fmt.Fprintln(os.Stderr, buildinfo.String())
	fmt.Fprintln(os.Stderr, "Phase 0 skeleton — server not yet implemented.")
	fmt.Fprintln(os.Stderr, "Track progress: README.md")
	os.Exit(0)
}
