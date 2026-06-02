package domain

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

// ============================================================
// Agent 状态机测试 —— TDD RED phase
// ============================================================

type AgentStatus string

const (
	StatusOffline  AgentStatus = "OFFLINE"
	StatusIdle     AgentStatus = "IDLE"
	StatusThinking AgentStatus = "THINKING"
	StatusWorking  AgentStatus = "WORKING"
	StatusWaiting  AgentStatus = "WAITING"
	StatusPaused   AgentStatus = "PAUSED"
)

// AgentStateMachine 管理 Agent 生命周期状态转换
type AgentStateMachine struct {
	status AgentStatus
}

func NewAgentStateMachine() *AgentStateMachine {
	return &AgentStateMachine{status: StatusOffline}
}

func (sm *AgentStateMachine) Current() AgentStatus {
	return sm.status
}

// ============================================================
// 测试：状态转换规则
// ============================================================

func TestAgentStateMachine_initialState_isOffline(t *testing.T) {
	sm := NewAgentStateMachine()
	assert.Equal(t, StatusOffline, sm.Current())
}

func TestAgentStateMachine_validTransitions(t *testing.T) {
	tests := []struct {
		name      string
		from      AgentStatus
		to        AgentStatus
		shouldSucceed bool
	}{
		// 合法的转换
		{name: "OFFLINE → IDLE (激活)", from: StatusOffline, to: StatusIdle, shouldSucceed: true},
		{name: "IDLE → THINKING (收到消息)", from: StatusIdle, to: StatusThinking, shouldSucceed: true},
		{name: "IDLE → WORKING (被分配任务)", from: StatusIdle, to: StatusWorking, shouldSucceed: true},
		{name: "THINKING → IDLE (回复完成)", from: StatusThinking, to: StatusIdle, shouldSucceed: true},
		{name: "WORKING → IDLE (任务完成)", from: StatusWorking, to: StatusIdle, shouldSucceed: true},
		{name: "IDLE → PAUSED (人类暂停)", from: StatusIdle, to: StatusPaused, shouldSucceed: true},
		{name: "THINKING → PAUSED (人类暂停)", from: StatusThinking, to: StatusPaused, shouldSucceed: true},
		{name: "WORKING → PAUSED (人类暂停)", from: StatusWorking, to: StatusPaused, shouldSucceed: true},
		{name: "PAUSED → IDLE (恢复)", from: StatusPaused, to: StatusIdle, shouldSucceed: true},
		{name: "WAITING → IDLE (解除阻塞)", from: StatusWaiting, to: StatusIdle, shouldSucceed: true},

		// 非法的转换
		{name: "OFFLINE → THINKING (跳过激活)", from: StatusOffline, to: StatusThinking, shouldSucceed: false},
		{name: "OFFLINE → WORKING (跳过激活)", from: StatusOffline, to: StatusWorking, shouldSucceed: false},
		{name: "IDLE → OFFLINE (非正常下线)", from: StatusIdle, to: StatusOffline, shouldSucceed: false},
		{name: "PAUSED → THINKING (暂停中不应推理)", from: StatusPaused, to: StatusThinking, shouldSucceed: false},
		{name: "PAUSED → WORKING (暂停中不应工作)", from: StatusPaused, to: StatusWorking, shouldSucceed: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sm := &AgentStateMachine{status: tt.from}
			err := sm.Transition(tt.to)

			if tt.shouldSucceed {
				assert.NoError(t, err)
				assert.Equal(t, tt.to, sm.Current())
			} else {
				assert.Error(t, err)
				assert.Equal(t, tt.from, sm.Current(), "非法转换不应改变状态")
			}
		})
	}
}

// Transition 的骨架实现 (被测对象)
func (sm *AgentStateMachine) Transition(to AgentStatus) error {
	// Phase 1: 简单实现，仅允许合法转换
	validTransitions := map[AgentStatus][]AgentStatus{
		StatusOffline:  {StatusIdle},
		StatusIdle:     {StatusThinking, StatusWorking, StatusPaused},
		StatusThinking: {StatusIdle, StatusPaused},
		StatusWorking:  {StatusIdle, StatusPaused},
		StatusWaiting:  {StatusIdle},
		StatusPaused:   {StatusIdle},
	}

	allowed, ok := validTransitions[sm.status]
	if !ok {
		return &InvalidTransitionError{From: sm.status, To: to}
	}

	for _, allowedTo := range allowed {
		if to == allowedTo {
			sm.status = to
			return nil
		}
	}

	return &InvalidTransitionError{From: sm.status, To: to}
}

type InvalidTransitionError struct {
	From, To AgentStatus
}

func (e *InvalidTransitionError) Error() string {
	return "invalid transition from " + string(e.From) + " to " + string(e.To)
}
