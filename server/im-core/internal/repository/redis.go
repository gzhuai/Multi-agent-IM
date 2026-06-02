package repository

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisStore wraps the Redis client.
type RedisStore struct {
	client *redis.Client
}

func NewRedisStore(ctx context.Context, addr, password string, db int) (*RedisStore, error) {
	client := redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: password,
		DB:       db,
	})
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("connect to redis: %w", err)
	}
	return &RedisStore{client: client}, nil
}

func (s *RedisStore) Client() *redis.Client {
	return s.client
}

func (s *RedisStore) Close() error {
	return s.client.Close()
}

func (s *RedisStore) Health(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return s.client.Ping(ctx).Err()
}
