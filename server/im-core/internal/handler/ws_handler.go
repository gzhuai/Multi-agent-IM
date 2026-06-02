package handler

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/multi-agent-im/im-core/internal/domain"
	"github.com/multi-agent-im/im-core/internal/service"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins in dev
	},
}

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = (pongWait * 9) / 10
	maxMessageSize = 65536
)

// WSHandler manages WebSocket connections.
type WSHandler struct {
	hub         *Hub
	msgService  *service.MessageService
}

func NewWSHandler(hub *Hub, msgService *service.MessageService) *WSHandler {
	return &WSHandler{hub: hub, msgService: msgService}
}

// HandleWebSocket upgrades an HTTP connection to WebSocket.
func (h *WSHandler) HandleWebSocket(w http.ResponseWriter, r *http.Request) {
	userID := r.Header.Get("X-User-ID")
	if userID == "" {
		userID = r.URL.Query().Get("user_id")
	}
	if userID == "" {
		http.Error(w, "user_id required", http.StatusUnauthorized)
		return
	}

	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}

	client := &Client{
		ID:       uuid.New().String(),
		UserID:   userID,
		Username: r.URL.Query().Get("username"),
		Conn:     conn,
		Send:     make(chan []byte, 256),
		Hub:      h.hub,
		LastPing: time.Now(),
	}

	h.hub.register <- client

	go h.writePump(client)
	go h.readPump(client)
}

// readPump reads messages from the WebSocket connection.
func (h *WSHandler) readPump(client *Client) {
	defer func() {
		h.hub.unregister <- client
		client.Conn.Close()
	}()

	client.Conn.SetReadLimit(maxMessageSize)
	client.Conn.SetReadDeadline(time.Now().Add(pongWait))
	client.Conn.SetPongHandler(func(string) error {
		client.Conn.SetReadDeadline(time.Now().Add(pongWait))
		client.LastPing = time.Now()
		return nil
	})

	for {
		_, raw, err := client.Conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Printf("WebSocket read error: %v", err)
			}
			break
		}

		var wsMsg struct {
			Type      string `json:"type"`
			ChannelID string `json:"channel_id"`
			Content   string `json:"content"`
			Mentions  []string `json:"mentions,omitempty"`
		}

		if err := json.Unmarshal(raw, &wsMsg); err != nil {
			log.Printf("Invalid message format: %v", err)
			continue
		}

		switch wsMsg.Type {
		case "message":
			msg := &domain.Message{
				ID:         uuid.New().String(),
				ChannelID:  wsMsg.ChannelID,
				SenderID:   client.UserID,
				SenderType: "human",
				SenderName: client.Username,
				Content:    wsMsg.Content,
				Mentions:   wsMsg.Mentions,
				CreatedAt:  time.Now(),
			}
			h.hub.BroadcastMessage(msg)

		case "subscribe":
			if wsMsg.ChannelID != "" {
				h.hub.Subscribe(wsMsg.ChannelID, client.ID)
				// Send channel history
				msgs, _ := h.msgService.GetChannelHistory(r.Context(), wsMsg.ChannelID, 50)
				historyPayload, _ := json.Marshal(map[string]interface{}{
					"type":     "history",
					"channel_id": wsMsg.ChannelID,
					"messages": msgs,
				})
				client.Send <- historyPayload
			}

		case "ping":
			client.Send <- []byte(`{"type":"pong"}`)
		}
	}
}

// writePump writes messages to the WebSocket connection.
func (h *WSHandler) writePump(client *Client) {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		client.Conn.Close()
	}()

	for {
		select {
		case message, ok := <-client.Send:
			client.Conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				client.Conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := client.Conn.WriteMessage(websocket.TextMessage, message); err != nil {
				return
			}

		case <-ticker.C:
			client.Conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := client.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// GetHistory returns recent messages for a channel.
func (h *WSHandler) GetHistory(w http.ResponseWriter, r *http.Request) {
	channelID := r.URL.Query().Get("channel_id")
	if channelID == "" {
		http.Error(w, "channel_id required", http.StatusBadRequest)
		return
	}

	msgs, err := h.msgService.GetChannelHistory(r.Context(), channelID, 50)
	if err != nil {
		http.Error(w, "failed to fetch history", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"messages": msgs,
	})
}
