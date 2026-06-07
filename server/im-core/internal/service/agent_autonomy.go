package service

import (
	"context"
	"log"
	"math/rand"
	"time"
)

// AutonomyManager periodically wakes idle agents so they can speak proactively.
type AutonomyManager struct {
	agentClient *AgentClient
	msgService  *MessageService
	ticker      *time.Ticker
	stopCh      chan struct{}
}

// NewAutonomyManager creates a new autonomy manager.
func NewAutonomyManager(agentClient *AgentClient, msgService *MessageService) *AutonomyManager {
	return &AutonomyManager{
		agentClient: agentClient,
		msgService:  msgService,
		stopCh:      make(chan struct{}),
	}
}

// Start begins the autonomous wake loop.
func (m *AutonomyManager) Start(interval time.Duration) {
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	m.ticker = time.NewTicker(interval)

	go func() {
		log.Printf("[Autonomy] Manager started (interval=%s)", interval)
		for {
			select {
			case <-m.ticker.C:
				m.wakeIdleAgents()
			case <-m.stopCh:
				m.ticker.Stop()
				log.Println("[Autonomy] Manager stopped")
				return
			}
		}
	}()
}

// Stop halts the autonomy loop.
func (m *AutonomyManager) Stop() {
	close(m.stopCh)
}

func (m *AutonomyManager) wakeIdleAgents() {
	ctx := context.Background()

	resp, err := m.agentClient.ListAgents(ctx)
	if err != nil {
		log.Printf("[Autonomy] Failed to list agents: %v", err)
		return
	}

	wakeCount := 0
	for _, agent := range resp.Agents {
		if agent.Status != "IDLE" {
			continue
		}

		// Get channels this agent belongs to
		channels, err := m.msgService.ListChannels(ctx, agent.ID)
		if err != nil || len(channels) == 0 {
			continue
		}

		// Pick a random group channel
		var groupChans []string
		for _, ch := range channels {
			if ch.Type == "group" {
				groupChans = append(groupChans, ch.ID)
			}
		}
		if len(groupChans) == 0 {
			continue
		}
		target := groupChans[rand.Intn(len(groupChans))]

		// Get channel participants for context
		members, _ := m.msgService.GetChannelMembers(ctx, target)
		participants := make([]map[string]interface{}, len(members))
		for i, m := range members {
			participants[i] = map[string]interface{}{
				"id": m.MemberID, "type": m.MemberType,
			}
		}

		// Wake agent in background
		go func(aid, chID string) {
			resp, err := m.agentClient.Wake(ctx, WakeRequest{
				AgentID:      aid,
				ChannelID:    chID,
				Participants: participants,
			})
			if err != nil {
				log.Printf("[Autonomy] Wake error for %s: %v", aid, err)
				return
			}
			if resp != nil && resp.Text != "" {
				log.Printf("[Autonomy] Agent %s spoke in channel %s", aid, chID)
			}
		}(agent.ID, target)

		wakeCount++
	}

	if wakeCount > 0 {
		log.Printf("[Autonomy] Woke %d agents", wakeCount)
	}
}
