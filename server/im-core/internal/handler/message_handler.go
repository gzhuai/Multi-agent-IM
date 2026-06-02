package handler

import (
	"encoding/json"
	"net/http"
)

// MessageHandler exposes REST endpoints for message operations.
type MessageHandler struct {
	wsHandler *WSHandler
}

func NewMessageHandler(wsHandler *WSHandler) *MessageHandler {
	return &MessageHandler{wsHandler: wsHandler}
}

func (h *MessageHandler) Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"service": "im-core",
	})
}

func (h *MessageHandler) GetHistory(w http.ResponseWriter, r *http.Request) {
	h.wsHandler.GetHistory(w, r)
}
