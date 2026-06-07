package handler

import (
	"encoding/json"
	"net/http"

	"github.com/multi-agent-im/im-core/internal/service"
)

type AuditHandler struct {
	auditService *service.AuditService
}

func NewAuditHandler(auditService *service.AuditService) *AuditHandler {
	return &AuditHandler{auditService: auditService}
}

func (h *AuditHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	path := r.URL.Path

	if r.Method == http.MethodGet && path == "/api/audit-logs/stats" {
		stats, err := h.auditService.AuditStats(r.Context())
		if err != nil {
			json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		json.NewEncoder(w).Encode(stats)
		return
	}

	if r.Method == http.MethodGet && path == "/api/audit-logs" {
		q := r.URL.Query()
		logs, err := h.auditService.QueryAuditLogs(r.Context(), service.AuditFilter{
			AgentID: q.Get("agent_id"),
			Action:  q.Get("action"),
			Since:   q.Get("since"),
			Limit:   100,
		})
		if err != nil {
			json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		json.NewEncoder(w).Encode(map[string]interface{}{"logs": logs, "count": len(logs)})
		return
	}

	json.NewEncoder(w).Encode(map[string]string{"error": "not found"})
}
