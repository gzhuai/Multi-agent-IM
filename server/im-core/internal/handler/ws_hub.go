package handler

import (
	"encoding/json"
	"log"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/multi-agent-im/im-core/internal/domain"
)

// Hub maintains the set of active WebSocket connections and routes messages.
type Hub struct {
	mu          sync.RWMutex
	connections map[string]*Client         // connectionID → Client
	users       map[string][]string        // userID → []connectionID
	channels    map[string]map[string]bool // channelID → set of connectionID

	// Callbacks
	onMessage        func(msg *domain.Message) error
	onChannelMessage func(msg *domain.Message) // fires for all non-agent messages in channels — main.go dispatches to group agents

	register   chan *Client
	unregister chan *Client
	broadcast  chan *domain.Message
}

type Client struct {
	ID           string
	UserID       string
	Username     string
	Conn         *websocket.Conn
	Send         chan []byte
	Hub          *Hub
	LastPing     time.Time
}

func NewHub(onMessage func(msg *domain.Message) error) *Hub {
	return &Hub{
		connections: make(map[string]*Client),
		users:       make(map[string][]string),
		channels:    make(map[string]map[string]bool),
		onMessage:   onMessage,
		register:    make(chan *Client),
		unregister:  make(chan *Client),
		broadcast:   make(chan *domain.Message),
	}
}

// SetChannelMessageHandler sets the callback fired for every non-agent message in a channel.
// Used to dispatch to all agents in a group channel.
func (h *Hub) SetChannelMessageHandler(handler func(msg *domain.Message)) {
	h.onChannelMessage = handler
}

func (h *Hub) Run() {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.connections[client.ID] = client
			h.users[client.UserID] = append(h.users[client.UserID], client.ID)
			h.mu.Unlock()
			log.Printf("Client connected: %s (user: %s)", client.ID, client.UserID)

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.connections[client.ID]; ok {
				delete(h.connections, client.ID)
				close(client.Send)
				// Remove from users
				conns := h.users[client.UserID]
				for i, cid := range conns {
					if cid == client.ID {
						h.users[client.UserID] = append(conns[:i], conns[i+1:]...)
						break
					}
				}
				// Remove from all channels
				for _, members := range h.channels {
					delete(members, client.ID)
				}
			}
			h.mu.Unlock()
			log.Printf("Client disconnected: %s", client.ID)

		case msg := <-h.broadcast:
			h.mu.RLock()
			// Send to all connections in the target channel
			if members, ok := h.channels[msg.ChannelID]; ok {
				payload, _ := json.Marshal(map[string]interface{}{
					"type":    "message",
					"message": msg,
				})
				for cid := range members {
					if client, ok := h.connections[cid]; ok {
						select {
						case client.Send <- payload:
						default:
							// Client's send buffer is full, skip
						}
					}
				}
			}
			h.mu.RUnlock()
		}
	}
}

// Subscribe adds a client to a channel's broadcast list.
func (h *Hub) Subscribe(channelID, connectionID string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.channels[channelID] == nil {
		h.channels[channelID] = make(map[string]bool)
	}
	h.channels[channelID][connectionID] = true
}

// Unsubscribe removes a client from a channel.
func (h *Hub) Unsubscribe(channelID, connectionID string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.channels[channelID] != nil {
		delete(h.channels[channelID], connectionID)
	}
}

// BroadcastMessage persists and broadcasts a message.
// For non-agent messages in group channels, notifies the channel handler to dispatch to all agents.
func (h *Hub) BroadcastMessage(msg *domain.Message) {
	if msg.ID == "" {
		msg.ID = uuid.New().String()
	}
	msg.CreatedAt = time.Now()

	if h.onMessage != nil {
		if err := h.onMessage(msg); err != nil {
			log.Printf("Error persisting message: %v", err)
		}
	}

	h.broadcast <- msg

	// Trigger channel-level agent dispatch for non-agent messages
	// (agents don't trigger other agents — prevents infinite loop)
	if h.onChannelMessage != nil && msg.SenderType != "agent" {
		go h.onChannelMessage(msg)
	}
}

// GetOnlineUsers returns the set of user IDs currently connected.
func (h *Hub) GetOnlineUsers() []string {
	h.mu.RLock()
	defer h.mu.RUnlock()
	seen := make(map[string]bool)
	for uid := range h.users {
		if len(h.users[uid]) > 0 {
			seen[uid] = true
		}
	}
	users := make([]string, 0, len(seen))
	for uid := range seen {
		users = append(users, uid)
	}
	return users
}
