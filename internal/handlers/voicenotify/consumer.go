package voicenotify

import (
	"encoding/json"
	"strings"
	"time"
)

// ConsumerMain implements the TTS queue consumer loop. Runs as `hook-observatory
// --tts-consumer`. Drains QueueFile and plays entries sequentially; exits after
// 3 seconds of idle, matching the Python consumer's self-cleaning behaviour.
func ConsumerMain() {
	writePID(ConsumerPIDFile)
	defer removePID(ConsumerPIDFile)

	idle := 0.0
	for idle < 3.0 {
		entries := DrainQueue()
		if len(entries) == 0 {
			sleep(500 * time.Millisecond)
			idle += 0.5
			continue
		}
		idle = 0.0
		for _, e := range entries {
			safePlay(e)
		}
	}
}

// CheckerMain implements the deferred-announcement checker loop. Runs as
// `hook-observatory --tts-checker <ident>`. Polls Redis until sub-agents have
// settled (or MaxWait elapses) then announces the pending message.
func CheckerMain(ident string) {
	ident = strings.TrimSpace(ident)
	if ident == "" {
		return
	}
	pidFile := checkerPIDPath(ident)
	writePID(pidFile)
	defer removePID(pidFile)

	// Ensure Redis is reachable before entering the loop.
	if GetRedis() == nil {
		return
	}

	interval := time.Duration(CheckerInterval) * time.Second
	maxWait := time.Duration(CheckerMaxWait) * time.Second
	settle := float64(SettleWindow)

	waited := time.Duration(0)
	for waited < maxWait {
		sleep(interval)
		waited += interval

		pending := GetPending(ident)
		if pending == "" {
			return // cancelled
		}

		if ActiveSubagents(ident) > 0 {
			continue
		}

		lastAct := LastActivityTs(ident)
		if lastAct > 0 && (nowSeconds()-lastAct) < settle {
			continue
		}

		// All clear — fire the pending announcement.
		firePending(pending)
		DelPending(ident)
		return
	}

	// MaxWait exceeded — force announce (fail-safe).
	if pending := GetPending(ident); pending != "" {
		firePending(pending)
		DelPending(ident)
	}
}

// firePending unmarshals the pending payload and enqueues the message. Matches
// the Python checker's behaviour: write to queue file first, fall back to
// direct playback only if no consumer is alive.
func firePending(raw string) {
	var payload struct {
		Msg string `json:"msg"`
	}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return
	}
	if payload.Msg == "" {
		return
	}
	// Always enqueue; consumer will pick it up, or Player falls through to
	// edge-tts/say if no consumer is running when we retry.
	EnqueueTTS(payload.Msg)
}

func safePlay(e QueueEntry) {
	defer func() { _ = recover() }()
	Play(e)
}

// checkerPIDPath mirrors Python's `/tmp/tts-checker-{ident_without_%}.pid`.
func checkerPIDPath(ident string) string {
	return "/tmp/tts-checker-" + strings.ReplaceAll(ident, "%", "") + ".pid"
}

// CheckerAlive returns true if a checker for the given identity is currently
// running (used by the main handler to avoid spawning duplicates).
func CheckerAlive(ident string) bool {
	return processAliveFromPID(checkerPIDPath(ident))
}

// SpawnChecker starts a detached checker process for the given identity.
func SpawnChecker(ident string) {
	if CheckerAlive(ident) {
		return
	}
	spawnDetached(SelfBinary(), "--tts-checker", ident)
}
