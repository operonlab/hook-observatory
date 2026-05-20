package clients

import (
	"context"
	"fmt"
	"os"
	"sync"
	"time"

	goredis "github.com/redis/go-redis/v9"

	"github.com/joneshong/hook-observatory/internal/core"
)

var (
	redisOnce   sync.Once
	redisClient *goredis.Client
)

// RedisClient returns the process-wide Redis client singleton.
// Returns nil if the connection cannot be established (fail-open semantics).
func RedisClient() *goredis.Client {
	redisOnce.Do(func() {
		// Priority: WORKSHOP_REDIS_URL env → config services → default
		url := os.Getenv("WORKSHOP_REDIS_URL")
		if url == "" {
			host := core.Cfg().GetService("redis_host")
			port := core.Cfg().GetService("redis_port")
			if host == "" {
				host = "localhost"
			}
			if port == "" {
				port = "6379"
			}
			url = fmt.Sprintf("redis://%s:%s/0", host, port)
		}
		opts, err := goredis.ParseURL(url)
		if err != nil {
			return
		}
		opts.DialTimeout = 3 * time.Second
		opts.ReadTimeout = 5 * time.Second
		opts.WriteTimeout = 5 * time.Second
		redisClient = goredis.NewClient(opts)
	})
	return redisClient
}

// HGet fetches a hash field. Returns ("", nil) if key/field missing.
func HGet(ctx context.Context, key, field string) (string, error) {
	r := RedisClient()
	if r == nil {
		return "", fmt.Errorf("redis: client not initialised")
	}
	val, err := r.HGet(ctx, key, field).Result()
	if err == goredis.Nil {
		return "", nil
	}
	return val, err
}

// HSet sets a hash field value.
func HSet(ctx context.Context, key, field, value string) error {
	r := RedisClient()
	if r == nil {
		return fmt.Errorf("redis: client not initialised")
	}
	return r.HSet(ctx, key, field, value).Err()
}

// Set sets a key with optional TTL (0 = no expiry).
func Set(ctx context.Context, key, value string, ttl time.Duration) error {
	r := RedisClient()
	if r == nil {
		return fmt.Errorf("redis: client not initialised")
	}
	return r.Set(ctx, key, value, ttl).Err()
}

// Get gets a key value. Returns ("", nil) if not found.
func Get(ctx context.Context, key string) (string, error) {
	r := RedisClient()
	if r == nil {
		return "", fmt.Errorf("redis: client not initialised")
	}
	val, err := r.Get(ctx, key).Result()
	if err == goredis.Nil {
		return "", nil
	}
	return val, err
}

// Publish sends a message to a Redis pub/sub channel.
func Publish(ctx context.Context, channel, message string) error {
	r := RedisClient()
	if r == nil {
		return fmt.Errorf("redis: client not initialised")
	}
	return r.Publish(ctx, channel, message).Err()
}
