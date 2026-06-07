package handler

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/multi-agent-im/im-core/internal/domain"
	"github.com/multi-agent-im/im-core/internal/service"
)

// ChannelHandler exposes REST endpoints for channel management.
type ChannelHandler struct {
	msgService *service.MessageService
}

func NewChannelHandler(msgService *service.MessageService) *ChannelHandler {
	return &ChannelHandler{msgService: msgService}
}

func (h *ChannelHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/channels")
	path = strings.TrimSuffix(path, "/")

	// POST /api/channels → create group channel
	if r.Method == http.MethodPost && path == "" {
		h.CreateChannel(w, r)
		return
	}

	// GET /api/channels → list user's channels
	if r.Method == http.MethodGet && path == "" {
		h.ListChannels(w, r)
		return
	}

	// /api/channels/{id}/members
	if strings.HasSuffix(path, "/members") {
		channelID := strings.TrimSuffix(path, "/members")
		channelID = strings.TrimPrefix(channelID, "/")

		if r.Method == http.MethodGet {
			h.GetMembers(w, r, channelID)
			return
		}
		if r.Method == http.MethodPost {
			h.AddMember(w, r, channelID)
			return
		}
	}

	http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
}

type createChannelRequest struct {
	Name    string   `json:"name"`
	OrgID   string   `json:"organization_id"`
	Members []memberRequest `json:"members"`
}

type memberRequest struct {
	ID   string `json:"id"`
	Type string `json:"type"` // "user" or "agent"
	Role string `json:"role"`
}

// CreateChannel handles POST /api/channels
func (h *ChannelHandler) CreateChannel(w http.ResponseWriter, r *http.Request) {
	var req createChannelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
		return
	}

	orgID := req.OrgID
	if orgID == "" {
		orgID = "2b711d7c-29b1-429c-b61d-e93ddaa46e41" // default org
	}
	creatorID := r.Header.Get("X-User-ID")
	if creatorID == "" {
		creatorID = r.URL.Query().Get("user_id")
	}

	channelID, err := h.msgService.CreateGroupChannel(r.Context(), orgID, req.Name, creatorID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}

	// Add additional members
	for _, m := range req.Members {
		role := m.Role
		if role == "" {
			role = "member"
		}
		_ = h.msgService.AddChannelMember(r.Context(), channelID, m.ID, m.Type, role)
	}

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"id":   channelID,
		"name": req.Name,
		"type": "group",
	})
}

// ListChannels handles GET /api/channels
func (h *ChannelHandler) ListChannels(w http.ResponseWriter, r *http.Request) {
	userID := r.Header.Get("X-User-ID")
	if userID == "" {
		userID = r.URL.Query().Get("user_id")
	}

	channels, err := h.msgService.ListChannels(r.Context(), userID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if channels == nil {
		channels = []domain.Channel{}
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"channels": channels})
}

// GetMembers handles GET /api/channels/{id}/members
func (h *ChannelHandler) GetMembers(w http.ResponseWriter, r *http.Request, channelID string) {
	members, err := h.msgService.GetChannelMembers(r.Context(), channelID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if members == nil {
		members = []domain.ChannelMember{}
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"members": members})
}

// AddMember handles POST /api/channels/{id}/members
func (h *ChannelHandler) AddMember(w http.ResponseWriter, r *http.Request, channelID string) {
	var req memberRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
		return
	}
	role := req.Role
	if role == "" {
		role = "member"
	}
	if err := h.msgService.AddChannelMember(r.Context(), channelID, req.ID, req.Type, role); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"ok": "true"})
}

func writeJSON(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}
