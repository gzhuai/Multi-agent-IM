package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type AgentClient struct {
	baseURL    string
	httpClient *http.Client
}

func NewAgentClient(baseURL string) *AgentClient {
	return &AgentClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 120 * time.Second,
		},
	}
}

// ── Think ─────────────────────────────────────────────────────

type ThinkRequest struct {
	AgentID      string                   `json:"agent_id"`
	ChannelID    string                   `json:"channel_id"`
	Messages     []map[string]interface{} `json:"messages"`
	Participants []map[string]interface{} `json:"participants,omitempty"`
}

type ThinkResponse struct {
	Text        string                   `json:"text"`
	Actions     []map[string]interface{} `json:"actions"`
	MemorySaved bool                     `json:"memory_saved"`
}

func (c *AgentClient) Think(ctx context.Context, req ThinkRequest) (*ThinkResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/api/think", c.baseURL), bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("agent runtime call failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("agent runtime returned %d: %s", resp.StatusCode, string(respBody))
	}

	var thinkResp ThinkResponse
	if err := json.NewDecoder(resp.Body).Decode(&thinkResp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &thinkResp, nil
}

// ── Wake (autonomous messaging) ───────────────────────────────

type WakeRequest struct {
	AgentID      string                   `json:"agent_id"`
	ChannelID    string                   `json:"channel_id"`
	Participants []map[string]interface{} `json:"participants,omitempty"`
}

func (c *AgentClient) Wake(ctx context.Context, req WakeRequest) (*ThinkResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal wake request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/api/wake", c.baseURL), bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create wake request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("wake call failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("wake returned %d: %s", resp.StatusCode, string(respBody))
	}

	var thinkResp ThinkResponse
	if err := json.NewDecoder(resp.Body).Decode(&thinkResp); err != nil {
		return nil, fmt.Errorf("decode wake response: %w", err)
	}
	return &thinkResp, nil
}

// ── Agent Management ──────────────────────────────────────────

type AgentInfo struct {
	ID      string      `json:"id"`
	Name    string      `json:"name"`
	Status  string      `json:"status"`
	Autonomy interface{} `json:"autonomy,omitempty"`
}

type ListAgentsResponse struct {
	Agents []AgentInfo `json:"agents"`
}

func (c *AgentClient) ListAgents(ctx context.Context) (*ListAgentsResponse, error) {
	httpReq, err := http.NewRequestWithContext(ctx, "GET",
		fmt.Sprintf("%s/api/agents", c.baseURL), nil)
	if err != nil {
		return nil, fmt.Errorf("create list request: %w", err)
	}

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("list agents failed: %w", err)
	}
	defer resp.Body.Close()

	var result ListAgentsResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode list: %w", err)
	}
	return &result, nil
}

func (c *AgentClient) PauseAgent(ctx context.Context, agentID string) error {
	req, _ := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/api/agents/%s/pause", c.baseURL, agentID), nil)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("pause agent returned %d", resp.StatusCode)
	}
	return nil
}

func (c *AgentClient) ResumeAgent(ctx context.Context, agentID string) error {
	req, _ := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/api/agents/%s/resume", c.baseURL, agentID), nil)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("resume agent returned %d", resp.StatusCode)
	}
	return nil
}
