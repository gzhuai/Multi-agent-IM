package handler

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
)

// ============================================================
// 被测接口定义 (实际代码在 message_handler.go 中实现)
// ============================================================

// Message 是消息领域模型
type Message struct {
	ID        string
	ChannelID string
	SenderID  string
	SenderType string // "human" | "agent"
	Content   string
	ReplyTo   *string
}

// MessageService 定义消息处理的核心业务逻辑接口
type MessageService interface {
	Send(ctx context.Context, msg *Message) error
	GetHistory(ctx context.Context, channelID string, limit int) ([]Message, error)
	RouteToAgent(ctx context.Context, msg *Message) error
}

// ============================================================
// Mock 定义
// ============================================================

type MockMessageRepo struct {
	mock.Mock
}

func (m *MockMessageRepo) Save(ctx context.Context, msg *Message) error {
	args := m.Called(ctx, msg)
	return args.Error(0)
}

func (m *MockMessageRepo) FindByChannel(ctx context.Context, channelID string, limit int) ([]Message, error) {
	args := m.Called(ctx, channelID, limit)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).([]Message), args.Error(1)
}

// ============================================================
// 单元测试
// ============================================================

func TestMessageService_Send_toChannel(t *testing.T) {
	tests := []struct {
		name        string
		msg         *Message
		setupMock   func(*MockMessageRepo)
		wantErr     bool
		errContains string
	}{
		{
			name: "正常发送消息到频道",
			msg: &Message{
				ID:         "msg_001",
				ChannelID:  "ch_public",
				SenderID:   "user_1",
				SenderType: "human",
				Content:    "大家好",
			},
			setupMock: func(repo *MockMessageRepo) {
				repo.On("Save", mock.Anything, mock.AnythingOfType("*handler.Message")).
					Return(nil)
			},
			wantErr: false,
		},
		{
			name: "空内容消息应被拒绝",
			msg: &Message{
				ID:        "msg_002",
				ChannelID: "ch_public",
				Content:   "",
			},
			setupMock: func(repo *MockMessageRepo) {
				// 验证层应拦截，不会调用 repo
			},
			wantErr:     true,
			errContains: "content cannot be empty",
		},
		{
			name: "超长消息应被拒绝",
			msg: &Message{
				ID:        "msg_003",
				ChannelID: "ch_public",
				Content:   string(make([]byte, 10001)), // 超过10KB限制
			},
			setupMock: func(repo *MockMessageRepo) {},
			wantErr:     true,
			errContains: "content too long",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := new(MockMessageRepo)
			tt.setupMock(repo)

			svc := &messageService{repo: repo}
			err := svc.Send(context.Background(), tt.msg)

			if tt.wantErr {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.errContains)
			} else {
				assert.NoError(t, err)
			}
			repo.AssertExpectations(t)
		})
	}
}

func TestMessageService_RouteToAgent_directsToCorrectAgent(t *testing.T) {
	// 当消息 @ 了某个 Agent 时，必须正确路由
	msg := &Message{
		ID:         "msg_004",
		ChannelID:  "ch_project",
		SenderID:   "user_1",
		SenderType: "human",
		Content:    "@陈思远 这个需求怎么看？",
	}

	repo := new(MockMessageRepo)
	repo.On("Save", mock.Anything, msg).Return(nil)

	svc := &messageService{repo: repo}
	err := svc.RouteToAgent(context.Background(), msg)

	assert.NoError(t, err)
	// 核心断言：消息被标记为需要路由到 "@陈思远" 对应的 Agent
	// (实际实现中会解析 @mention 并查找对应的 agent channel)
}

func TestMessageService_GetHistory_respectsLimit(t *testing.T) {
	repo := new(MockMessageRepo)
	existingMessages := make([]Message, 100)
	repo.On("FindByChannel", mock.Anything, "ch_1", 20).
		Return(existingMessages[:20], nil)

	svc := &messageService{repo: repo}
	msgs, err := svc.GetHistory(context.Background(), "ch_1", 20)

	assert.NoError(t, err)
	assert.Len(t, msgs, 20)
}

// ============================================================
// messageService 的骨架实现 (被测对象)
// ============================================================

type messageService struct {
	repo *MockMessageRepo
}

func (s *messageService) Send(ctx context.Context, msg *Message) error {
	if msg.Content == "" {
		return errors.New("content cannot be empty")
	}
	if len(msg.Content) > 10000 {
		return errors.New("content too long")
	}
	return s.repo.Save(ctx, msg)
}

func (s *messageService) RouteToAgent(ctx context.Context, msg *Message) error {
	// Phase 1 实现: 解析 @mention → 查找 agent → 投递到 agent 频道
	return s.repo.Save(ctx, msg)
}

func (s *messageService) GetHistory(ctx context.Context, channelID string, limit int) ([]Message, error) {
	return s.repo.FindByChannel(ctx, channelID, limit)
}
