package handler

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/multi-agent-im/im-core/internal/service"
)

type ExportHandler struct {
	msgService *service.MessageService
}

func NewExportHandler(msgService *service.MessageService) *ExportHandler {
	return &ExportHandler{msgService: msgService}
}

func (h *ExportHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	// GET /api/export/chat/{channel_id}?format=md
	path := strings.TrimPrefix(r.URL.Path, "/api/export/chat/")
	channelID := strings.TrimSuffix(path, "/")
	format := r.URL.Query().Get("format")
	if format == "" {
		format = "md"
	}

	messages, err := h.msgService.GetChannelHistory(r.Context(), channelID, 200)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}

	switch format {
	case "json":
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{"channel_id": channelID, "messages": messages})

	case "md":
		w.Header().Set("Content-Type", "text/markdown; charset=utf-8")
		w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=chat-%s.md", channelID[:8]))
		var sb strings.Builder
		sb.WriteString(fmt.Sprintf("# Channel %s — Chat Export\n\n", channelID[:8]))
		for _, m := range messages {
			senderType := m.SenderType
			if senderType == "" {
				senderType = "human"
			}
			senderName := m.SenderName
			if senderName == "" {
				senderName = m.SenderID[:8]
			}
			sb.WriteString(fmt.Sprintf("**[%s] %s** (%s)\n", senderType, senderName, m.CreatedAt.Format("2006-01-02 15:04")))
			sb.WriteString(fmt.Sprintf("%s\n\n", m.Content))
		}
		w.Write([]byte(sb.String()))

	default:
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "unsupported format"})
	}
}

