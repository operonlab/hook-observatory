package handlers

// read_edit_ratio.go — Go port of handlers/read_edit_ratio.py
//
// PostToolUse / Read|Edit|Write: tracks Read vs Edit/Write calls per session.
// When the model edits files without reading them first (blind-edit anti-pattern),
// emits a warning message and fires background notifications.
//
// Thresholds (from empirical data):
//   - Good:    read:edit ratio >= 4.0, blind edit rate < 10%
//   - Warning: ratio < 3.0 OR blind edit rate > 25%
//   - Alert:   ratio < 2.0 OR blind edit rate > 35%
//
// State: /tmp/.read-edit-ratio-{hash12}.json (per-session)

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
	portregistry "github.com/joneshong/workshop/libs/go-port-registry"
)

// rerBarkServer points at the bark notification daemon (port 8090 in the
// registry). Resolved at init so yaml is single source of truth.
var rerBarkServer = portregistry.URL("bark", "", 8090)

const (
	rerBarkDeviceKey = "gx7KnK5f8iAKuqNLWzy5hP"

	rerMinEditsForWarn = 5
	rerRatioWarn       = 3.0
	rerRatioAlert      = 2.0
	rerBlindWarn       = 0.25
	rerBlindAlert      = 0.35
	rerWarnCooldownS   = 300 // 5 min
)

// NOTE: Not registered. Python handlers/__init__.py does not import or register
// read_edit_ratio — it's inactive in production. Keeping the implementation for
// future opt-in, but no core.Register() call to preserve parity.
func init() {}

// rerState mirrors the JSON fields stored in /tmp/.read-edit-ratio-<hash>.json
type rerState struct {
	Reads      []string `json:"reads"`
	ReadCount  int      `json:"read_count"`
	EditCount  int      `json:"edit_count"`
	BlindEdits int      `json:"blind_edits"`
	LastWarnAt float64  `json:"last_warn_at"`
	StartedAt  float64  `json:"started_at"`
}

func rerStatePath(sessionID string) string {
	h := sha256.Sum256([]byte(sessionID))
	hex12 := fmt.Sprintf("%x", h[:6]) // 12 hex chars
	return filepath.Join(os.TempDir(), fmt.Sprintf(".read-edit-ratio-%s.json", hex12))
}

func rerLoad(path string) rerState {
	data, err := os.ReadFile(path)
	if err != nil {
		return rerState{}
	}
	var s rerState
	if err := json.Unmarshal(data, &s); err != nil {
		return rerState{}
	}
	return s
}

func rerSave(path string, s rerState) {
	data, err := json.Marshal(s)
	if err != nil {
		return
	}
	_ = os.WriteFile(path, data, 0o644)
}

func rerExtractSessionID(rawInput string) string {
	var parsed map[string]any
	if err := json.Unmarshal([]byte(rawInput), &parsed); err != nil {
		return "default"
	}
	if v, ok := parsed["session_id"].(string); ok && v != "" {
		return v
	}
	return "default"
}

func rerExtractFilePath(toolInput map[string]any) string {
	if v, ok := toolInput["file_path"].(string); ok {
		return v
	}
	return ""
}

func readEditRatioHandle(_, toolName string, toolInput map[string]any, rawInput string) core.HookResult {
	sessionID := rerExtractSessionID(rawInput)
	sp := rerStatePath(sessionID)
	state := rerLoad(sp)

	if state.ReadCount == 0 && state.EditCount == 0 && state.StartedAt == 0 {
		state = rerState{
			Reads:     []string{},
			StartedAt: float64(time.Now().UnixNano()) / 1e9,
		}
	}

	filePath := rerExtractFilePath(toolInput)

	if toolName == "Read" {
		state.ReadCount++
		if filePath != "" && !rerContains(state.Reads, filePath) {
			state.Reads = append(state.Reads, filePath)
			if len(state.Reads) > 500 {
				state.Reads = state.Reads[len(state.Reads)-500:]
			}
		}
		rerSave(sp, state)
		return core.Allow()
	}

	// Edit or Write
	state.EditCount++
	if filePath != "" && !rerContains(state.Reads, filePath) {
		state.BlindEdits++
	}

	editCount := state.EditCount
	readCount := state.ReadCount
	blindEdits := state.BlindEdits
	rerSave(sp, state)

	// Not enough data yet
	if editCount < rerMinEditsForWarn {
		return core.Allow()
	}

	ratio := float64(readCount) / float64(editCount)
	blindRate := float64(blindEdits) / float64(editCount)

	// Check cooldown
	now := float64(time.Now().UnixNano()) / 1e9
	if now-state.LastWarnAt < rerWarnCooldownS {
		return core.Allow()
	}

	isAlert := ratio < rerRatioAlert || blindRate > rerBlindAlert
	isWarn := ratio < rerRatioWarn || blindRate > rerBlindWarn

	if !isAlert && !isWarn {
		return core.Allow()
	}

	// Update cooldown
	state.LastWarnAt = now
	rerSave(sp, state)

	severity := "🟡"
	if isAlert {
		severity = "🔴"
	}

	msg := fmt.Sprintf(
		"%s [read:edit ratio] R:E=%.1f (目標≥4.0), 盲改率=%.0f%% (%d/%d), reads=%d edits=%d",
		severity, ratio, blindRate*100, blindEdits, editCount, readCount, editCount,
	)
	if isAlert {
		msg += " — 模型可能進入淺思考模式, 建議重啟 session"
	}

	// Fire-and-forget notifications
	rerNotify(severity, ratio, blindRate, isAlert)

	return core.Message(msg)
}

func rerContains(slice []string, s string) bool {
	for _, v := range slice {
		if v == s {
			return true
		}
	}
	return false
}

func rerNotify(severity string, ratio float64, blindRate float64, isAlert bool) {
	title := severity + " Read:Edit Ratio"
	body := fmt.Sprintf("R:E=%.1f, 盲改率=%.0f%%", ratio, blindRate*100)
	if isAlert {
		body += " — 建議重啟 session"
	}

	// macOS notification
	osaBody := rerEscapeOSA(body)
	osaTitle := rerEscapeOSA(title)
	osaCmd := fmt.Sprintf(
		`osascript -e 'display notification "%s" with title "%s" sound name "Sosumi"'`,
		osaBody, osaTitle,
	)
	_ = core.RunBackground([]string{"sh", "-c", osaCmd}, "")

	// Bark push
	sound := "bell"
	level := "active"
	if isAlert {
		sound = "alarm"
		level = "timeSensitive"
	}
	barkURL := fmt.Sprintf(
		"%s/%s/%s/%s?group=hook-observatory&sound=%s&level=%s",
		rerBarkServer, rerBarkDeviceKey,
		url.PathEscape(title), url.PathEscape(body),
		sound, level,
	)
	_ = core.RunBackground([]string{"curl", "-sf", barkURL}, "")
}

func rerEscapeOSA(s string) string {
	// Escape double-quotes and backslashes for osascript string literals
	out := ""
	for _, ch := range s {
		switch ch {
		case '"':
			out += `\"`
		case '\\':
			out += `\\`
		default:
			out += string(ch)
		}
	}
	return out
}
