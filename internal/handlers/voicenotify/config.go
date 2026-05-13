// Package voicenotify — Go port of stations/hook-observatory/handlers/voice_notify.py.
//
// The Python version was 839 LOC orchestrating:
//   - Redis-backed debounce + sub-agent activity counter
//   - File-queue (flock-protected JSONL) + detached consumer process
//   - Deferred announcement with background checker process
//   - Three-layer TTS fallback: Workshop stations/tts HTTP → edge-tts → macOS say
//
// This Go version keeps the same behaviour but collapses the process topology:
// the consumer and checker run as `hook-dispatcher --tts-consumer` /
// `hook-dispatcher --tts-checker <ident>` self-exec modes, so we no longer
// ship a Python script template as a string.
package voicenotify

import (
	"os"
	"path/filepath"
	"strconv"

	portregistry "github.com/joneshong/hook-dispatcher/internal/portregistry"
)

// Env-overridable configuration.
//
// Defaults target the Workshop TTS station (stations/tts — FastAPI at :10201)
// using its real `/synthesize` endpoint, which accepts query parameters and
// returns `{audio_path, ...}`. The previous default URL (`/api/tts/speak`)
// never existed on this station — it was inherited verbatim from
// voice_notify.py, where every request silently 404'd and fell through to the
// edge-tts branch. The Go port now actually exercises the station so
// operators can swap engines centrally (apple / qwen3-tts / kokoro / ...).
var (
	TTSURL       = envOr("CLAUDE_TTS_URL", portregistry.URL("tts", "/synthesize", 10201))
	TTSEngine    = envOr("CLAUDE_TTS_ENGINE", "edge")
	TTSVoice     = envOr("CLAUDE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
	Voice        = envOr("CLAUDE_VOICE_ID", "zh-CN-XiaoxiaoNeural") // edge-tts fallback
	Rate         = envOr("CLAUDE_VOICE_RATE", "+20%")               // edge-tts fallback
	PlaybackVol  = envOr("CLAUDE_VOICE_VOLUME", "0.4")
	WebuiURL     = envOr("TMUX_WEBUI_URL", portregistry.URL("tmux-webui", "", 10105))
	DebounceTTL  = envOrInt("CLAUDE_VOICE_DEBOUNCE", 20)
	SettleWindow = envOrInt("CLAUDE_VOICE_SETTLE", 8)
)

const (
	QueueFile         = "/tmp/claude-tts-queue.jsonl"
	ConsumerPIDFile   = "/tmp/claude-tts-consumer.pid"
	ActiveAgentsTTL   = 300
	CheckerInterval   = 2
	CheckerMaxWait    = 45
	SubagentSoundPath = "/System/Library/Sounds/Pop.aiff"
	redisHost         = "127.0.0.1"
	redisPort         = 6379
	redisTimeoutSec   = 2
)

// SubagentSoundEnabled mirrors CLAUDE_SUBAGENT_SOUND=1 opt-in.
func SubagentSoundEnabled() bool {
	return os.Getenv("CLAUDE_SUBAGENT_SOUND") == "1"
}

// SubagentVolume mirrors CLAUDE_SUBAGENT_VOLUME, default 0.3.
func SubagentVolume() string {
	return envOr("CLAUDE_SUBAGENT_VOLUME", "0.3")
}

// SelfBinary returns the path to the currently running hook-dispatcher binary.
// Used to self-exec for consumer/checker modes.
func SelfBinary() string {
	exe, err := os.Executable()
	if err != nil || exe == "" {
		// Fallback to PATH lookup
		return "hook-dispatcher"
	}
	// Resolve symlinks so `make install` + ~/.local/bin symlink still works.
	if resolved, err := filepath.EvalSymlinks(exe); err == nil {
		return resolved
	}
	return exe
}

// AskPhrases are the "請示" phrases played on PreToolUse/AskUserQuestion.
var AskPhrases = []string{
	"少爺，維恩有問題想請示您",
	"少爺，這裡需要您做個決定",
	"少爺，請您過目這幾個選項",
	"少爺，維恩需要您的指示",
	"少爺，有個問題想請教您",
}

// NumCN maps 0-9 to Chinese numerals (for tmux pane labels).
var NumCN = []string{"零", "一", "二", "三", "四", "五", "六", "七", "八", "九"}

// TeammateTypes are agent/subagent types that should never trigger Stop TTS.
var TeammateTypes = map[string]bool{
	"Plan":               true,
	"Explore":            true,
	"Code":               true,
	"Debug":              true,
	"Review":             true,
	"worker":             true,
	"explorer":           true,
	"reviewer":           true,
	"designer":           true,
	"foreman":            true,
	"researcher":         true,
	"browser":            true,
	"media":              true,
	"codex-dispatcher":   true,
	"gemini-dispatcher":  true,
	"copilot-dispatcher": true,
	"writer":             true,
	"statusline-setup":   true,
	"claude-code-guide":  true,
	"audit-context-building:function-analyzer": true,
	"chaos-engineer":  true,
	"general-purpose": true,
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envOrInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}
