// voice_notify.go — Go in-process TTS notification handler.
//
// Replaces the former Python-bridge implementation with a pure-Go port of
// stations/hook-observatory/handlers/voice_notify.py. Redis state machine,
// queue file, deferred checker, and three-layer TTS playback all live in
// internal/handlers/voicenotify.
//
// The queue consumer and deferred-announcement checker run as self-exec
// modes of the hook-dispatcher binary (`--tts-consumer`, `--tts-checker
// <ident>`), so there is no longer any Python subprocess in this handler.
package handlers

import (
	"github.com/joneshong/hook-dispatcher/internal/core"
	"github.com/joneshong/hook-dispatcher/internal/handlers/voicenotify"
)

func init() {
	// PreToolUse/AskUserQuestion → 請示 phrase
	core.Register("PreToolUse", core.Entry{
		Matcher:    "AskUserQuestion",
		Handler:    voiceNotifyHandle,
		ModuleName: "voice_notify",
	})
	entry := core.Entry{
		Handler:    voiceNotifyHandle,
		ModuleName: "voice_notify",
	}
	core.Register("Stop", entry)
	core.Register("SubagentStart", entry)
	core.Register("SubagentStop", entry)
}

// voiceNotifyHandle delegates synchronously to the in-process voicenotify
// package. Long-running work (actual TTS playback, deferred checker) runs in
// detached self-exec children — those outlive this process — but the Redis /
// queue bookkeeping must finish before we return, otherwise the child
// consumer has nothing to drain when the short-lived dispatcher exits.
func voiceNotifyHandle(eventType, toolName string, _ map[string]any, raw string) core.HookResult {
	voicenotify.Handle(eventType, toolName, raw)
	return core.Allow()
}
