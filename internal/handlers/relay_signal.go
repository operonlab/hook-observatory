package handlers

// relay_signal.go — Go port of handlers/relay_signal.py
//
// Stop handler: checks if a tmux-relay is waiting for this pane, signals via
// `tmux wait-for -S`, and updates Redis pane cache.

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	rclient "github.com/joneshong/hook-dispatcher/internal/clients"
	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("Stop", core.Entry{
		Matcher:    "",
		Handler:    relaySignalHandle,
		Critical:   false,
		ModuleName: "relay_signal",
	})
}

func relaySignalHandle(_, _ string, _ map[string]any, _ string) core.HookResult {
	paneID := os.Getenv("TMUX_PANE")
	if paneID == "" {
		return core.Allow()
	}
	pane := strings.TrimPrefix(paneID, "%")
	pendingFile := fmt.Sprintf("/tmp/relay-pending-%s.channel", pane)

	if _, err := os.Stat(pendingFile); os.IsNotExist(err) {
		relayDebugLog(fmt.Sprintf("no-op pane=%s (no pending file)", pane))
		return core.Allow()
	}

	data, err := os.ReadFile(pendingFile)
	if err != nil {
		relayDebugLog(fmt.Sprintf("error pane=%s (cannot read pending file)", pane))
		return core.Allow()
	}

	channel := strings.TrimSpace(string(data))
	if channel == "" {
		return core.Allow()
	}

	// Remove pending file before signalling to avoid double-fire.
	_ = os.Remove(pendingFile)
	_ = core.RunBackground([]string{"tmux", "wait-for", "-S", channel}, "")
	relayDebugLog(fmt.Sprintf("signaled pane=%s channel=%s", pane, channel))

	// Advisory Redis cache update — fail-open.
	relayUpdateRedisCache(pane)

	return core.Allow()
}

func relayUpdateRedisCache(pane string) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	raw, err := rclient.HGet(ctx, "relay:panes", pane)
	if err != nil || raw == "" {
		return
	}

	var info map[string]any
	if err := json.Unmarshal([]byte(raw), &info); err != nil {
		return
	}

	signalFile, _ := info["signal_file"].(string)
	info["status"] = "idle"
	info["updated_at"] = time.Now().Unix()

	updated, err := json.Marshal(info)
	if err == nil {
		_ = rclient.HSet(ctx, "relay:panes", pane, string(updated))
	}

	if signalFile != "" {
		basename := filepath.Base(signalFile)
		result := map[string]any{
			"status":       "success",
			"completed_at": time.Now().Unix(),
			"pane":         "%" + pane,
		}
		resultJSON, _ := json.Marshal(result)
		_ = rclient.Set(ctx, "relay:result:"+basename, string(resultJSON), time.Hour)
	}

	_ = rclient.Set(ctx, "relay:cache_ts", fmt.Sprintf("%f", float64(time.Now().UnixNano())/1e9), time.Minute)
}

func relayDebugLog(msg string) {
	f, err := os.OpenFile("/tmp/relay-signal-debug.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	ts := time.Now().Format("15:04:05")
	_, _ = fmt.Fprintf(f, "%s %s\n", ts, msg)
}
