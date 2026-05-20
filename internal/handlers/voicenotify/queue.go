package voicenotify

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// EnqueueTTS appends a JSON line to QueueFile (flock-protected) and makes sure
// a consumer process is running.  Fail-open: any error is silently swallowed.
func EnqueueTTS(msg string) {
	entry := QueueEntry{
		Text:  msg,
		Voice: Voice,
		Rate:  Rate,
		Vol:   PlaybackVol,
	}
	line, err := json.Marshal(&entry)
	if err != nil {
		return
	}

	f, err := os.OpenFile(QueueFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	if _, err := f.Write(append(line, '\n')); err != nil {
		return
	}
	_ = f.Sync()

	ensureConsumer()
}

// ensureConsumer spawns `hook-observatory --tts-consumer` detached if no
// consumer is currently alive.
func ensureConsumer() {
	if consumerAlive() {
		return
	}
	spawnDetached(SelfBinary(), "--tts-consumer")
}

func consumerAlive() bool {
	return processAliveFromPID(ConsumerPIDFile)
}

// ProcessAliveFromPID exposes process-alive check (used in checker too).
func processAliveFromPID(pidFile string) bool {
	b, err := os.ReadFile(pidFile)
	if err != nil {
		return false
	}
	pidStr := strings.TrimSpace(string(b))
	pid, err := strconv.Atoi(pidStr)
	if err != nil || pid <= 0 {
		return false
	}
	p, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	// On Unix, FindProcess always succeeds; Signal(0) verifies liveness.
	return p.Signal(syscall.Signal(0)) == nil
}

// spawnDetached starts an independent child process (session-detached) so it
// outlives the parent hook-observatory invocation.
func spawnDetached(name string, args ...string) {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		return
	}
	// Let the child be fully detached — don't Wait() (parent will exit).
	_ = cmd.Process.Release()
}

// DrainQueue atomically reads all entries from QueueFile and truncates it.
// Mirrors the Python consumer's drain() — including the "don't create an
// empty file if nothing has been enqueued yet" guard.
func DrainQueue() []QueueEntry {
	if _, err := os.Stat(QueueFile); err != nil {
		return nil
	}
	f, err := os.OpenFile(QueueFile, os.O_RDWR, 0o644)
	if err != nil {
		return nil
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return nil
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)

	var out []QueueEntry
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 256*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var e QueueEntry
		if err := json.Unmarshal([]byte(line), &e); err == nil {
			out = append(out, e)
		}
	}
	// Truncate after successful read.
	_ = f.Truncate(0)
	_, _ = f.Seek(0, 0)
	return out
}

// writePID records the current process PID to the given file (best-effort).
func writePID(pidFile string) {
	_ = os.WriteFile(pidFile, []byte(strconv.Itoa(os.Getpid())), 0o644)
}

// removePID removes the PID file (used on consumer/checker exit).
func removePID(pidFile string) {
	_ = os.Remove(pidFile)
}

// sleep is a named wrapper so tests can override.
var sleep = func(d time.Duration) { time.Sleep(d) }
