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

// ── Channel management ──────────────────────────────────────────

// CreateGroupChannel creates a new group channel.
func (s *MessageService) CreateGroupChannel(ctx context.Context, orgID, name, creatorID string) (string, error) {
	if s.db == nil {
		return "", fmt.Errorf("database not available")
	}
	// Use orgID as a fallback creator if creatorID is not a UUID
	creatorUUID := creatorID
	if len(creatorID) != 36 || creatorID[8] != '-' {
		creatorUUID = orgID // fallback to org owner
	}
	var channelID string
	err := s.db.Pool().QueryRow(ctx,
		`INSERT INTO channels (organization_id, name, type, is_agent_channel, created_by)
		 VALUES ($1, $2, 'group', true, $3::uuid) RETURNING id`,
		orgID, name, creatorUUID,
	).Scan(&channelID)
	if err != nil {
		return "", fmt.Errorf("create group channel: %w", err)
	}
	// Add creator as admin member
	_, _ = s.db.Pool().Exec(ctx,
		`INSERT INTO channel_members (channel_id, member_id, member_type, role)
		 VALUES ($1, $2, 'user', 'admin') ON CONFLICT DO NOTHING`,
		channelID, creatorID,
	)
	return channelID, nil
}

// AddChannelMember adds a user or agent to a channel.
func (s *MessageService) AddChannelMember(ctx context.Context, channelID, memberID, memberType, role string) error {
	if s.db == nil {
		return fmt.Errorf("database not available")
	}
	_, err := s.db.Pool().Exec(ctx,
		`INSERT INTO channel_members (channel_id, member_id, member_type, role)
		 VALUES ($1::uuid, $2, $3, $4) ON CONFLICT DO NOTHING`,
		channelID, memberID, memberType, role,
	)
	return err
}

// GetChannelMembers returns all members of a channel.
func (s *MessageService) GetChannelMembers(ctx context.Context, channelID string) ([]domain.ChannelMember, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	rows, err := s.db.Pool().Query(ctx,
		`SELECT member_id, member_type, role FROM channel_members WHERE channel_id = $1`,
		channelID,
	)
	if err != nil {
		return nil, fmt.Errorf("query channel members: %w", err)
	}
	defer rows.Close()

	var members []domain.ChannelMember
	for rows.Next() {
		var m domain.ChannelMember
		if err := rows.Scan(&m.MemberID, &m.MemberType, &m.Role); err != nil {
			return nil, fmt.Errorf("scan member: %w", err)
		}
		members = append(members, m)
	}
	return members, nil
}

// ListChannels returns channels the user is a member of.
func (s *MessageService) ListChannels(ctx context.Context, userID string) ([]domain.Channel, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	rows, err := s.db.Pool().Query(ctx,
		`SELECT c.id, c.organization_id, c.name, c.type, c.is_agent_channel, c.created_by, c.created_at
		 FROM channels c
		 INNER JOIN channel_members cm ON cm.channel_id = c.id
		 WHERE cm.member_id = $1
		 ORDER BY c.created_at DESC`,
		userID,
	)
	if err != nil {
		return nil, fmt.Errorf("list channels: %w", err)
	}
	defer rows.Close()

	var channels []domain.Channel
	for rows.Next() {
		var ch domain.Channel
		if err := rows.Scan(&ch.ID, &ch.OrganizationID, &ch.Name, &ch.Type,
			&ch.IsAgentChannel, &ch.CreatedBy, &ch.CreatedAt); err != nil {
			return nil, fmt.Errorf("scan channel: %w", err)
		}
		channels = append(channels, ch)
	}
	return channels, nil
}

// GetChannelAgents returns agent IDs that are members of a channel.
func (s *MessageService) GetChannelAgents(ctx context.Context, channelID string) ([]string, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	rows, err := s.db.Pool().Query(ctx,
		`SELECT member_id FROM channel_members
		 WHERE channel_id = $1 AND member_type = 'agent'`,
		channelID,
	)
	if err != nil {
		return nil, fmt.Errorf("query channel agents: %w", err)
	}
	defer rows.Close()

	var agentIDs []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("scan agent id: %w", err)
		}
		agentIDs = append(agentIDs, id)
	}
	return agentIDs, nil
}

// Ensure time import is used (needed by domain model)
var _ = time.Now
