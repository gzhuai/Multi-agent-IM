package service

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/multi-agent-im/im-core/internal/domain"
	"github.com/multi-agent-im/im-core/internal/repository"
)

type MessageService struct {
	db    *repository.PostgresStore
	redis *repository.RedisStore
}

func NewMessageService(db *repository.PostgresStore, redis *repository.RedisStore) *MessageService {
	return &MessageService{db: db, redis: redis}
}

func (s *MessageService) ValidateAndSend(ctx context.Context, msg *domain.Message) error {
	if msg.Content == "" {
		return errors.New("content cannot be empty")
	}
	if len(msg.Content) > 10000 {
		return errors.New("content too long")
	}
	return s.PersistMessage(ctx, msg)
}

func (s *MessageService) PersistMessage(ctx context.Context, msg *domain.Message) error {
	if s.db == nil {
		return fmt.Errorf("database not available")
	}

	const query = `
		INSERT INTO messages (id, channel_id, sender_id, sender_type, content, reply_to, created_at)
		VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
	`
	contentJSON := fmt.Sprintf(`{"type":"text","body":%q}`, msg.Content)

	_, err := s.db.Pool().Exec(ctx, query,
		msg.ID, msg.ChannelID, msg.SenderID, msg.SenderType,
		contentJSON, msg.ReplyTo, msg.CreatedAt,
	)
	return err
}

func (s *MessageService) GetChannelHistory(ctx context.Context, channelID string, limit int) ([]domain.Message, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}

	const query = `
		SELECT id, channel_id, sender_id, sender_type,
		       content->>'body' as body, reply_to, created_at
		FROM messages
		WHERE channel_id = $1
		ORDER BY created_at DESC
		LIMIT $2
	`
	rows, err := s.db.Pool().Query(ctx, query, channelID, limit)
	if err != nil {
		return nil, fmt.Errorf("query messages: %w", err)
	}
	defer rows.Close()

	var messages []domain.Message
	for rows.Next() {
		var msg domain.Message
		if err := rows.Scan(&msg.ID, &msg.ChannelID, &msg.SenderID,
			&msg.SenderType, &msg.Content, &msg.ReplyTo, &msg.CreatedAt); err != nil {
			return nil, fmt.Errorf("scan message: %w", err)
		}
		messages = append(messages, msg)
	}
	// Reverse to chronological order
	for i, j := 0, len(messages)-1; i < j; i, j = i+1, j-1 {
		messages[i], messages[j] = messages[j], messages[i]
	}
	return messages, nil
}

// GetOrCreateDirectChannel finds or creates a 1v1 channel between two users.
func (s *MessageService) GetOrCreateDirectChannel(ctx context.Context, orgID, user1, user2 string) (string, error) {
	if s.db == nil {
		return "", fmt.Errorf("database not available")
	}

	// Generate a deterministic channel name for direct messages
	chName := fmt.Sprintf("dm-%s-%s", user1[:8], user2[:8])

	var channelID string
	err := s.db.Pool().QueryRow(ctx,
		`INSERT INTO channels (organization_id, name, type, is_agent_channel, created_by)
		 VALUES ($1, $2, 'direct', false, $3)
		 ON CONFLICT DO NOTHING
		 RETURNING id`,
		orgID, chName, user1,
	).Scan(&channelID)

	if err != nil {
		// Channel already exists, fetch it
		err = s.db.Pool().QueryRow(ctx,
			`SELECT id FROM channels WHERE organization_id=$1 AND name=$2`,
			orgID, chName,
		).Scan(&channelID)
		if err != nil {
			return "", fmt.Errorf("create channel: %w", err)
		}
	}

	// Ensure both users are members
	for _, uid := range []string{user1, user2} {
		_, _ = s.db.Pool().Exec(ctx,
			`INSERT INTO channel_members (channel_id, member_id, member_type, role)
			 VALUES ($1, $2, 'user', 'member')
			 ON CONFLICT DO NOTHING`,
			channelID, uid,
		)
	}

	return channelID, nil
}

// Ensure time import is used (needed by domain model)
var _ = time.Now
