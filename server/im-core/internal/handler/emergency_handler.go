package handler

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/multi-agent-im/im-core/internal/service"
)

type EmergencyHandler struct {
	agentClient *service.AgentClient
	msgService  *service.MessageService
	auditSvc    *service.AuditService
}

func NewEmergencyHandler(agentClient *service.AgentClient, msgService *service.MessageService, auditSvc *service.AuditService) *EmergencyHandler {
	return &EmergencyHandler{agentClient: agentClient, msgService: msgService, auditSvc: auditSvc}
}

func (h *EmergencyHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	path := strings.TrimPrefix(r.URL.Path, "/api/emergency")

	if r.Method != http.MethodPost {
		json.NewEncoder(w).Encode(map[string]string{"error": "method not allowed"})
		return
	}

	ctx := r.Context()

	switch path {
	case "/pause-all":
		resp, err := h.agentClient.ListAgents(ctx)
		if err != nil {
			json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		count := 0
		for _, a := range resp.Agents {
			if a.Status == "OFFLINE" {
				continue
			}
			h.agentClient.PauseAgent(ctx, a.ID)
			count++
		}
		h.auditSvc.LogActionSimple(ctx, "", "emergency_pause_all", "paused "+strconv.Itoa(count)+" agents")
		json.NewEncoder(w).Encode(map[string]interface{}{"ok": true, "paused": count})
	case "/resume-all":
		resp, err := h.agentClient.ListAgents(ctx)
		if err != nil {
			json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		count := 0
		for _, a := range resp.Agents {
			if a.Status != "PAUSED" {
				continue
			}
			h.agentClient.ResumeAgent(ctx, a.ID)
			count++
		}
		h.auditSvc.LogActionSimple(ctx, "", "emergency_resume_all", "resumed "+strconv.Itoa(count)+" agents")
		json.NewEncoder(w).Encode(map[string]interface{}{"ok": true, "resumed": count})
	default:
		json.NewEncoder(w).Encode(map[string]string{"error": "not found"})
	}
}
