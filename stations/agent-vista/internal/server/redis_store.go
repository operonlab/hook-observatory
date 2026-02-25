// Package server — RedisStore persists agent state to Redis so it survives backend restarts.
package server

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/joneshong/agent-vista/internal/protocol"
)

const (
	redisKeyAgentSet = "vista:agents"       // SET of agent IDs
	redisKeyPrefix   = "vista:agent:"       // HASH per agent
	redisKeySeq      = "vista:seq"          // last event sequence
	redisAgentTTL    = 24 * time.Hour       // auto-expire stale agents
)

// RedisStore wraps a Redis client for agent state persistence.
type RedisStore struct {
	client  *redis.Client
	verbose bool
}

// NewRedisStore creates a Redis-backed store. Returns an error if the connection fails.
func NewRedisStore(redisURL string, verbose bool) (*RedisStore, error) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, err
	}
	client := redis.NewClient(opts)

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		client.Close()
		return nil, err
	}

	if verbose {
		log.Printf("[redis] connected to %s", redisURL)
	}
	return &RedisStore{client: client, verbose: verbose}, nil
}

// SaveAgent persists an agent's state to Redis.
func (r *RedisStore) SaveAgent(agent *protocol.AgentState) {
	ctx := context.Background()
	key := redisKeyPrefix + agent.ID

	data, err := json.Marshal(agent)
	if err != nil {
		log.Printf("[redis] marshal error for %s: %v", agent.ID, err)
		return
	}

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, redisAgentTTL)
	pipe.SAdd(ctx, redisKeyAgentSet, agent.ID)
	if _, err := pipe.Exec(ctx); err != nil {
		log.Printf("[redis] save error for %s: %v", agent.ID, err)
	}
}

// RemoveAgent deletes an agent from Redis.
func (r *RedisStore) RemoveAgent(id string) {
	ctx := context.Background()
	pipe := r.client.Pipeline()
	pipe.Del(ctx, redisKeyPrefix+id)
	pipe.SRem(ctx, redisKeyAgentSet, id)
	if _, err := pipe.Exec(ctx); err != nil {
		log.Printf("[redis] remove error for %s: %v", id, err)
	}
}

// LoadAll returns all persisted agent states from Redis.
func (r *RedisStore) LoadAll() ([]protocol.AgentState, error) {
	ctx := context.Background()

	ids, err := r.client.SMembers(ctx, redisKeyAgentSet).Result()
	if err != nil {
		return nil, err
	}
	if len(ids) == 0 {
		return nil, nil
	}

	// Pipeline MGET for all agents
	keys := make([]string, len(ids))
	for i, id := range ids {
		keys[i] = redisKeyPrefix + id
	}
	vals, err := r.client.MGet(ctx, keys...).Result()
	if err != nil {
		return nil, err
	}

	var agents []protocol.AgentState
	var staleIDs []string
	for i, val := range vals {
		if val == nil {
			// Key expired but still in the set — mark for cleanup
			staleIDs = append(staleIDs, ids[i])
			continue
		}
		str, ok := val.(string)
		if !ok {
			continue
		}
		var agent protocol.AgentState
		if err := json.Unmarshal([]byte(str), &agent); err != nil {
			log.Printf("[redis] unmarshal error for %s: %v", ids[i], err)
			continue
		}
		agents = append(agents, agent)
	}

	// Clean up stale set entries
	if len(staleIDs) > 0 {
		staleMembers := make([]interface{}, len(staleIDs))
		for i, id := range staleIDs {
			staleMembers[i] = id
		}
		r.client.SRem(ctx, redisKeyAgentSet, staleMembers...)
	}

	if r.verbose {
		log.Printf("[redis] loaded %d agents from Redis", len(agents))
	}
	return agents, nil
}

// SaveSeq persists the latest event sequence number.
func (r *RedisStore) SaveSeq(seq uint64) {
	ctx := context.Background()
	r.client.Set(ctx, redisKeySeq, seq, 0)
}

// LoadSeq returns the last persisted event sequence number.
func (r *RedisStore) LoadSeq() uint64 {
	ctx := context.Background()
	val, err := r.client.Get(ctx, redisKeySeq).Uint64()
	if err != nil {
		return 0
	}
	return val
}

// Close shuts down the Redis connection.
func (r *RedisStore) Close() error {
	return r.client.Close()
}
