package domain

import "time"

// AgentStatus represents the lifecycle state of a digital employee.
type AgentStatus string

const (
	AgentStatusOffline  AgentStatus = "OFFLINE"
	AgentStatusIdle     AgentStatus = "IDLE"
	AgentStatusThinking AgentStatus = "THINKING"
	AgentStatusWorking  AgentStatus = "WORKING"
	AgentStatusWaiting  AgentStatus = "WAITING"
	AgentStatusPaused   AgentStatus = "PAUSED"
)

// Message represents an IM message.
type Message struct {
	ID         string     `json:"id"`
	ChannelID  string     `json:"channel_id"`
	SenderID   string     `json:"sender_id"`
	SenderType string     `json:"sender_type"`
	SenderName string     `json:"sender_name"`
	Content    string     `json:"content"`
	ReplyTo    *string    `json:"reply_to,omitempty"`
	Mentions   []string   `json:"mentions,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
}

// Channel represents a communication channel.
type Channel struct {
	ID             string    `json:"id"`
	OrganizationID string    `json:"organization_id"`
	Name           string    `json:"name"`
	Type           string    `json:"type"` // direct, group, department, project
	IsAgentChannel bool      `json:"is_agent_channel"`
	CreatedBy      string    `json:"created_by"`
	CreatedAt      time.Time `json:"created_at"`
}

// ChannelMember represents a member of a channel.
type ChannelMember struct {
	MemberID    string `json:"member_id"`
	MemberType  string `json:"member_type"` // user, agent
	Role        string `json:"role"`
	DisplayName string `json:"display_name"`
}

// Task represents a work item assigned to an agent.
type Task struct {
	ID           string     `json:"id"`
	Title        string     `json:"title"`
	Description  string     `json:"description"`
	CreatorID    string     `json:"creator_id"`
	CreatorType  string     `json:"creator_type"`
	AssigneeID   string     `json:"assignee_id"`
	ParentTaskID *string    `json:"parent_task_id,omitempty"`
	ChannelID    *string    `json:"channel_id,omitempty"`
	Status       string     `json:"status"`
	Priority     string     `json:"priority"`
	ArtifactURLs []string   `json:"artifact_urls,omitempty"`
	Deadline     *time.Time `json:"deadline,omitempty"`
	CompletedAt  *time.Time `json:"completed_at,omitempty"`
	SubtaskIDs   []string   `json:"subtask_ids,omitempty"`
	CreatedAt    time.Time  `json:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
}

// AgentStateMachine manages valid transitions between AgentStatus values.
type AgentStateMachine struct {
	status AgentStatus
}

func NewAgentStateMachine() *AgentStateMachine {
	return &AgentStateMachine{status: AgentStatusOffline}
}

func (sm *AgentStateMachine) Current() AgentStatus {
	return sm.status
}

var validTransitions = map[AgentStatus][]AgentStatus{
	AgentStatusOffline:  {AgentStatusIdle},
	AgentStatusIdle:     {AgentStatusThinking, AgentStatusWorking, AgentStatusPaused},
	AgentStatusThinking: {AgentStatusIdle, AgentStatusPaused},
	AgentStatusWorking:  {AgentStatusIdle, AgentStatusPaused},
	AgentStatusWaiting:  {AgentStatusIdle},
	AgentStatusPaused:   {AgentStatusIdle},
}

type InvalidTransitionError struct {
	From, To AgentStatus
}

func (e *InvalidTransitionError) Error() string {
	return "invalid transition from " + string(e.From) + " to " + string(e.To)
}

func (sm *AgentStateMachine) Transition(to AgentStatus) error {
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
