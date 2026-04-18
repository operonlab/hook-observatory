package core

import (
	"context"
	"os/exec"
	"time"
)

// CmdResult mirrors the pieces of subprocess.CompletedProcess that handlers use.
type CmdResult struct {
	Stdout   string
	Stderr   string
	ExitCode int
	TimedOut bool
}

// RunCmd runs a subprocess with timeout + fail-safe semantics.
//
// Mirrors base.run_cmd from handlers/base.py.
// Returns nil on unrecoverable error (exec not found, start failed).
// On timeout the process is killed and TimedOut=true is set.
func RunCmd(args []string, stdin string, timeout time.Duration, cwd string) *CmdResult {
	if len(args) == 0 {
		return nil
	}
	if timeout <= 0 {
		timeout = 10 * time.Second
	}

	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, args[0], args[1:]...)
	if cwd != "" {
		cmd.Dir = cwd
	}
	if stdin != "" {
		cmd.Stdin = readerFromString(stdin)
	}

	stdoutBuf := newBoundedBuffer(4 * 1024 * 1024)
	stderrBuf := newBoundedBuffer(4 * 1024 * 1024)
	cmd.Stdout = stdoutBuf
	cmd.Stderr = stderrBuf

	err := cmd.Run()
	res := &CmdResult{
		Stdout:   stdoutBuf.String(),
		Stderr:   stderrBuf.String(),
		ExitCode: 0,
	}
	if ctx.Err() == context.DeadlineExceeded {
		res.TimedOut = true
		res.ExitCode = -1
		return res
	}
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			res.ExitCode = exitErr.ExitCode()
			return res
		}
		return nil
	}
	return res
}

// RunBackground starts a fire-and-forget subprocess, detached from the parent.
// Returns an error if the process could not be started.
func RunBackground(args []string, cwd string) error {
	if len(args) == 0 {
		return nil
	}
	cmd := exec.Command(args[0], args[1:]...)
	if cwd != "" {
		cmd.Dir = cwd
	}
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }() // reap to avoid zombies
	return nil
}
