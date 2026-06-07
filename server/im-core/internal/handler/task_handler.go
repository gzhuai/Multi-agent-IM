package handler

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/multi-agent-im/im-core/internal/service"
)

// TaskHandler exposes REST endpoints for task management.
type TaskHandler struct {
	taskService *service.TaskService
}

func NewTaskHandler(taskService *service.TaskService) *TaskHandler {
	return &TaskHandler{taskService: taskService}
}

func (h *TaskHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/tasks")
	path = strings.TrimSuffix(path, "/")

	w.Header().Set("Content-Type", "application/json")

	// GET /api/tasks/stats
	if r.Method == http.MethodGet && path == "/stats" {
		h.GetStats(w, r)
		return
	}

	// POST /api/tasks → create
	if r.Method == http.MethodPost && path == "" {
		h.CreateTask(w, r)
		return
	}

	// GET /api/tasks → list
	if r.Method == http.MethodGet && path == "" {
		h.ListTasks(w, r)
		return
	}

	// /api/tasks/{id}/subtasks
	if strings.HasSuffix(path, "/subtasks") && r.Method == http.MethodPost {
		taskID := strings.TrimSuffix(path, "/subtasks")
		taskID = strings.TrimPrefix(taskID, "/")
		h.AddSubtask(w, r, taskID)
		return
	}

	// /api/tasks/{id}/status
	if strings.HasSuffix(path, "/status") && r.Method == http.MethodPatch {
		taskID := strings.TrimSuffix(path, "/status")
		taskID = strings.TrimPrefix(taskID, "/")
		h.UpdateStatus(w, r, taskID)
		return
	}

	// /api/tasks/{id}/assign
	if strings.HasSuffix(path, "/assign") && r.Method == http.MethodPatch {
		taskID := strings.TrimSuffix(path, "/assign")
		taskID = strings.TrimPrefix(taskID, "/")
		h.AssignTask(w, r, taskID)
		return
	}

	// GET /api/tasks/{id}
	if r.Method == http.MethodGet && path != "" {
		taskID := strings.TrimPrefix(path, "/")
		h.GetTask(w, r, taskID)
		return
	}

	json.NewEncoder(w).Encode(map[string]string{"error": "not found"})
}

// ── Handlers ────────────────────────────────────────────────────

func (h *TaskHandler) CreateTask(w http.ResponseWriter, r *http.Request) {
	var req service.CreateTaskRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "invalid body"})
		return
	}
	if req.Priority == "" {
		req.Priority = "NORMAL"
	}
	if req.CreatorType == "" {
		req.CreatorType = "human"
	}
	if req.CreatorID == "" {
		req.CreatorID = r.Header.Get("X-User-ID")
	}

	task, err := h.taskService.CreateTask(r.Context(), req)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(task)
}

func (h *TaskHandler) ListTasks(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	filter := service.TaskFilter{
		AssigneeID:   q.Get("assignee_id"),
		Status:       q.Get("status"),
		ChannelID:    q.Get("channel_id"),
		OnlyTopLevel: q.Get("top_level") == "true",
	}
	if pid := q.Get("parent_task_id"); pid != "" {
		filter.ParentTaskID = &pid
	}

	tasks, err := h.taskService.ListTasks(r.Context(), filter)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	json.NewEncoder(w).Encode(map[string]interface{}{"tasks": tasks, "count": len(tasks)})
}

func (h *TaskHandler) GetTask(w http.ResponseWriter, r *http.Request, taskID string) {
	task, err := h.taskService.GetTask(r.Context(), taskID)
	if err != nil {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{"error": "task not found"})
		return
	}
	// Also fetch subtasks
	pid := task.ID
	subtasks, _ := h.taskService.ListTasks(r.Context(), service.TaskFilter{ParentTaskID: &pid})
	json.NewEncoder(w).Encode(map[string]interface{}{
		"task":     task,
		"subtasks": subtasks,
	})
}

func (h *TaskHandler) UpdateStatus(w http.ResponseWriter, r *http.Request, taskID string) {
	var req struct {
		Status string `json:"status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Status == "" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "status required"})
		return
	}

	task, err := h.taskService.UpdateTaskStatus(r.Context(), taskID, req.Status)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	json.NewEncoder(w).Encode(task)
}

func (h *TaskHandler) AssignTask(w http.ResponseWriter, r *http.Request, taskID string) {
	var req struct {
		AssigneeID string `json:"assignee_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.AssigneeID == "" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "assignee_id required"})
		return
	}

	task, err := h.taskService.AssignTask(r.Context(), taskID, req.AssigneeID)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	json.NewEncoder(w).Encode(task)
}

func (h *TaskHandler) AddSubtask(w http.ResponseWriter, r *http.Request, parentID string) {
	var req struct {
		Title       string `json:"title"`
		Description string `json:"description"`
		AssigneeID  string `json:"assignee_id"`
		Priority    string `json:"priority"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Title == "" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "title required"})
		return
	}

	subtask, err := h.taskService.AddSubtask(r.Context(), parentID, req.Title, req.Description, req.AssigneeID, req.Priority)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(subtask)
}

func (h *TaskHandler) GetStats(w http.ResponseWriter, r *http.Request) {
	stats, err := h.taskService.GetTaskStats(r.Context())
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	json.NewEncoder(w).Encode(stats)
}

// ensure time import is used
var _ = time.Now
