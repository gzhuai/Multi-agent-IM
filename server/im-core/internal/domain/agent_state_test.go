package domain

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestAgentStateMachine_initialState_isOffline(t *testing.T) {
	sm := NewAgentStateMachine()
	assert.Equal(t, AgentStatusOffline, sm.Current())
}

func TestAgentStateMachine_validTransitions(t *testing.T) {
	tests := []struct {
		name          string
		from          AgentStatus
		to            AgentStatus
		shouldSucceed bool
	}{
		// Valid transitions
		{name: "OFFLINE → IDLE (activate)", from: AgentStatusOffline, to: AgentStatusIdle, shouldSucceed: true},
		{name: "IDLE → THINKING (receive message)", from: AgentStatusIdle, to: AgentStatusThinking, shouldSucceed: true},
		{name: "IDLE → WORKING (assigned task)", from: AgentStatusIdle, to: AgentStatusWorking, shouldSucceed: true},
		{name: "THINKING → IDLE (reply done)", from: AgentStatusThinking, to: AgentStatusIdle, shouldSucceed: true},
		{name: "WORKING → IDLE (task done)", from: AgentStatusWorking, to: AgentStatusIdle, shouldSucceed: true},
		{name: "IDLE → PAUSED (human pause)", from: AgentStatusIdle, to: AgentStatusPaused, shouldSucceed: true},
		{name: "THINKING → PAUSED (human pause)", from: AgentStatusThinking, to: AgentStatusPaused, shouldSucceed: true},
		{name: "WORKING → PAUSED (human pause)", from: AgentStatusWorking, to: AgentStatusPaused, shouldSucceed: true},
		{name: "PAUSED → IDLE (resume)", from: AgentStatusPaused, to: AgentStatusIdle, shouldSucceed: true},
		{name: "WAITING → IDLE (unblock)", from: AgentStatusWaiting, to: AgentStatusIdle, shouldSucceed: true},

		// Invalid transitions
		{name: "OFFLINE → THINKING (skip activate)", from: AgentStatusOffline, to: AgentStatusThinking, shouldSucceed: false},
		{name: "OFFLINE → WORKING (skip activate)", from: AgentStatusOffline, to: AgentStatusWorking, shouldSucceed: false},
		{name: "IDLE → OFFLINE (invalid shutdown)", from: AgentStatusIdle, to: AgentStatusOffline, shouldSucceed: false},
		{name: "PAUSED → THINKING (shouldn't think when paused)", from: AgentStatusPaused, to: AgentStatusThinking, shouldSucceed: false},
		{name: "PAUSED → WORKING (shouldn't work when paused)", from: AgentStatusPaused, to: AgentStatusWorking, shouldSucceed: false},
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
				assert.Equal(t, tt.from, sm.Current(), "illegal transition should not change state")
			}
		})
	}
}
