package handler

import (
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/multi-agent-im/im-core/internal/domain"
	"github.com/multi-agent-im/im-core/internal/service"
)

type WebhookHandler struct {
	msgService *service.MessageService
	hub        *Hub
}

func NewWebhookHandler(msgService *service.MessageService, hub *Hub) *WebhookHandler {
	return &WebhookHandler{msgService: msgService, hub: hub}
}

func (h *WebhookHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method == http.MethodPost && r.URL.Path == "/api/webhooks/slack" {
		var req struct {
			Text      string `json:"text"`
			ChannelID string `json:"channel_id"`
			UserName  string `json:"user_name"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Text == "" {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]string{"error": "text and channel_id required"})
			return
		}
		if req.ChannelID == "" {
			req.ChannelID = "general"
		}

		msg := &domain.Message{
			ID:         uuid.New().String(),
			ChannelID:  req.ChannelID,
			SenderID:   "slack-webhook",
			SenderType: "system",
			SenderName: req.UserName,
			Content:    "[Slack] " + req.Text,
		}
		h.hub.BroadcastMessage(msg)
		json.NewEncoder(w).Encode(map[string]interface{}{"ok": true, "message_id": msg.ID})
		return
	}

	json.NewEncoder(w).Encode(map[string]string{"error": "not found"})
}
