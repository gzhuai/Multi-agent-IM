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
			Timeout: 60 * time.Second, // LLM calls can take time
		},
	}
}

type ThinkRequest struct {
	AgentID      string   `json:"agent_id"`
	ChannelID    string   `json:"channel_id"`
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
