package voicenotify

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"sync"
	"time"

	redis "github.com/redis/go-redis/v9"
)

// Singleton client. Lazy-init; on connection failure we cache a "disabled"
// sentinel so subsequent calls skip the dial attempt.
var (
	redisOnce    sync.Once
	redisClient  *redis.Client
	redisEnabled bool
)

// GetRedis returns a connected client or nil. Fail-open: TTS must never block.
func GetRedis() *redis.Client {
	redisOnce.Do(func() {
		client := redis.NewClient(&redis.Options{
			Addr:         fmt.Sprintf("%s:%d", redisHost, redisPort),
			DialTimeout:  time.Duration(redisTimeoutSec) * time.Second,
			ReadTimeout:  time.Duration(redisTimeoutSec) * time.Second,
			WriteTimeout: time.Duration(redisTimeoutSec) * time.Second,
		})
		ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
		defer cancel()
		if err := client.Ping(ctx).Err(); err != nil {
			_ = client.Close()
			return
		}
		redisClient = client
		redisEnabled = true
	})
	if !redisEnabled {
		return nil
	}
	return redisClient
}

// GetIdent returns the stable identity used for Redis keys.
// Priority: TMUX_PANE > session_id > ppid fallback.
func GetIdent(sessionID string) string {
	if pane := os.Getenv("TMUX_PANE"); pane != "" {
		return pane
	}
	if sessionID != "" {
		return sessionID
	}
	return fmt.Sprintf("pid-%d", os.Getppid())
}

// DebounceOK implements the two-layer debounce: per-event + shared completion
// cooldown. Returns true when the TTS may proceed.
func DebounceOK(eventType, sessionID string) bool {
	if DebounceTTL <= 0 {
		return true
	}
	r := GetRedis()
	if r == nil {
		return true
	}
	ident := GetIdent(sessionID)
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()

	key := fmt.Sprintf("tts:debounce:%s:%s", ident, eventType)
	ok, err := r.SetNX(ctx, key, 1, time.Duration(DebounceTTL)*time.Second).Result()
	if err != nil {
		return true
	}
	if !ok {
		return false
	}
	if eventType == "stop" || eventType == "subagent_stop" {
		cooldownKey := fmt.Sprintf("tts:cooldown:%s", ident)
		ok2, err2 := r.SetNX(ctx, cooldownKey, 1, time.Duration(DebounceTTL)*time.Second).Result()
		if err2 != nil {
			return true
		}
		if !ok2 {
			return false
		}
	}
	return true
}

func activeKey(ident string) string   { return fmt.Sprintf("tts:active_agents:%s", ident) }
func lastActKey(ident string) string  { return fmt.Sprintf("tts:last_activity:%s", ident) }
func pendingKey(ident string) string  { return fmt.Sprintf("tts:pending:%s", ident) }

// TrackSubagentStart increments the active-agent counter and cancels any
// pending deferred announcement.
func TrackSubagentStart(ident string) {
	r := GetRedis()
	if r == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	pipe := r.Pipeline()
	pipe.Incr(ctx, activeKey(ident))
	pipe.Expire(ctx, activeKey(ident), time.Duration(ActiveAgentsTTL)*time.Second)
	pipe.Set(ctx, lastActKey(ident), fmt.Sprintf("%f", nowSeconds()), time.Duration(ActiveAgentsTTL)*time.Second)
	pipe.Del(ctx, pendingKey(ident))
	_, _ = pipe.Exec(ctx)
}

// TrackSubagentStop decrements the counter and refreshes last_activity.
// Floors the counter at 0 if a missed Start left it negative.
func TrackSubagentStop(ident string) {
	r := GetRedis()
	if r == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	pipe := r.Pipeline()
	pipe.Decr(ctx, activeKey(ident))
	pipe.Expire(ctx, activeKey(ident), time.Duration(ActiveAgentsTTL)*time.Second)
	pipe.Set(ctx, lastActKey(ident), fmt.Sprintf("%f", nowSeconds()), time.Duration(ActiveAgentsTTL)*time.Second)
	_, _ = pipe.Exec(ctx)

	val, err := r.Get(ctx, activeKey(ident)).Result()
	if err != nil {
		return
	}
	if n, err := strconv.Atoi(val); err == nil && n < 0 {
		r.Set(ctx, activeKey(ident), 0, time.Duration(ActiveAgentsTTL)*time.Second)
	}
}

// ActiveSubagents returns the count, or 0 on error / missing key.
func ActiveSubagents(ident string) int {
	r := GetRedis()
	if r == nil {
		return 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	val, err := r.Get(ctx, activeKey(ident)).Result()
	if err != nil {
		return 0
	}
	n, _ := strconv.Atoi(val)
	return n
}

// LastActivityTs returns the last activity timestamp (seconds since epoch).
// Zero if not set.
func LastActivityTs(ident string) float64 {
	r := GetRedis()
	if r == nil {
		return 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	val, err := r.Get(ctx, lastActKey(ident)).Result()
	if err != nil {
		return 0
	}
	f, _ := strconv.ParseFloat(val, 64)
	return f
}

// CancelPendingTTS removes the deferred announcement key (if any).
func CancelPendingTTS(ident string) {
	r := GetRedis()
	if r == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	_ = r.Del(ctx, pendingKey(ident)).Err()
}

// SetPending writes the deferred announcement payload (JSON string) with TTL.
func SetPending(ident, payload string) error {
	r := GetRedis()
	if r == nil {
		return fmt.Errorf("redis unavailable")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	return r.Set(ctx, pendingKey(ident), payload, time.Duration(CheckerMaxWait+10)*time.Second).Err()
}

// GetPending reads the deferred announcement payload, or empty string.
func GetPending(ident string) string {
	r := GetRedis()
	if r == nil {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	val, err := r.Get(ctx, pendingKey(ident)).Result()
	if err != nil {
		return ""
	}
	return val
}

// DelPending removes the deferred announcement key.
func DelPending(ident string) {
	r := GetRedis()
	if r == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(redisTimeoutSec)*time.Second)
	defer cancel()
	_ = r.Del(ctx, pendingKey(ident)).Err()
}

func nowSeconds() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}
