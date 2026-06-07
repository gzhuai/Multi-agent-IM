package service

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/multi-agent-im/im-core/internal/domain"
	"github.com/multi-agent-im/im-core/internal/repository"
)

// TaskService manages the full task lifecycle.
type TaskService struct {
	db *repository.PostgresStore
}

func NewTaskService(db *repository.PostgresStore) *TaskService {
	return &TaskService{db: db}
}

// ── CRUD ───────────────────────────────────────────────────────

// CreateTask inserts a new task. Returns the created task with generated ID.
func (s *TaskService) CreateTask(ctx context.Context, req CreateTaskRequest) (*domain.Task, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}

	// Handle IDs: creator_id must be valid UUID for the FK constraint
	creatorID := req.CreatorID
	if len(creatorID) != 36 || creatorID[8] != '-' {
		creatorID = uuid.New().String()
	}

	id := uuid.New().String()
	now := time.Now()

	_, err := s.db.Pool().Exec(ctx, `
		INSERT INTO tasks (id, title, description, creator_id, creator_type,
			assignee_id, parent_task_id, channel_id, status, priority, deadline, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$12)`,
		id, req.Title, req.Description, creatorID, req.CreatorType,
		nilIfEmpty(req.AssigneeID), nilIfEmptyP(req.ParentTaskID), nilIfEmptyP(req.ChannelID),
		"TODO", req.Priority, req.Deadline, now,
	)
	if err != nil {
		return nil, fmt.Errorf("insert task: %w", err)
	}

	task := &domain.Task{
		ID:           id,
		Title:        req.Title,
		Description:  req.Description,
		CreatorID:    req.CreatorID,
		CreatorType:  req.CreatorType,
		AssigneeID:   req.AssigneeID,
		ParentTaskID: req.ParentTaskID,
		ChannelID:    req.ChannelID,
		Status:       "TODO",
		Priority:     req.Priority,
		Deadline:     req.Deadline,
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	return task, nil
}

type CreateTaskRequest struct {
	Title        string     `json:"title"`
	Description  string     `json:"description"`
	CreatorID    string     `json:"creator_id"`
	CreatorType  string     `json:"creator_type"`
	AssigneeID   string     `json:"assignee_id"`
	ParentTaskID *string    `json:"parent_task_id,omitempty"`
	ChannelID    *string    `json:"channel_id,omitempty"`
	Priority     string     `json:"priority"`
	Deadline     *time.Time `json:"deadline,omitempty"`
}

// GetTask fetches a single task by ID.
func (s *TaskService) GetTask(ctx context.Context, taskID string) (*domain.Task, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	var t domain.Task
	var deadline, completedAt *time.Time
	err := s.db.Pool().QueryRow(ctx, `
		SELECT id, title, description, creator_id, creator_type, assignee_id,
			parent_task_id, channel_id, status, priority,
			deadline, completed_at, created_at, updated_at
		FROM tasks WHERE id = $1`, taskID,
	).Scan(&t.ID, &t.Title, &t.Description, &t.CreatorID, &t.CreatorType,
		&t.AssigneeID, &t.ParentTaskID, &t.ChannelID, &t.Status, &t.Priority,
		&deadline, &completedAt, &t.CreatedAt, &t.UpdatedAt)
	if err != nil {
		return nil, fmt.Errorf("get task: %w", err)
	}
	if deadline != nil && !deadline.IsZero() {
		t.Deadline = deadline
	}
	if completedAt != nil && !completedAt.IsZero() {
		t.CompletedAt = completedAt
	}
	return &t, nil
}

// ListTasks returns tasks matching optional filters.
func (s *TaskService) ListTasks(ctx context.Context, filter TaskFilter) ([]domain.Task, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	query := `SELECT id, title, description, creator_id, creator_type, assignee_id,
		parent_task_id, channel_id, status, priority, deadline, completed_at, created_at, updated_at
		FROM tasks WHERE 1=1`
	args := []interface{}{}
	argIdx := 1

	if filter.AssigneeID != "" {
		query += fmt.Sprintf(" AND assignee_id = $%d", argIdx)
		args = append(args, filter.AssigneeID)
		argIdx++
	}
	if filter.Status != "" {
		query += fmt.Sprintf(" AND status = $%d", argIdx)
		args = append(args, filter.Status)
		argIdx++
	}
	if filter.ChannelID != "" {
		query += fmt.Sprintf(" AND channel_id = $%d", argIdx)
		args = append(args, filter.ChannelID)
		argIdx++
	}
	if filter.ParentTaskID != nil && *filter.ParentTaskID != "" {
		query += fmt.Sprintf(" AND parent_task_id = $%d", argIdx)
		args = append(args, *filter.ParentTaskID)
		argIdx++
	} else if filter.OnlyTopLevel {
		query += " AND parent_task_id IS NULL"
	}
	query += " ORDER BY created_at DESC LIMIT 100"

	rows, err := s.db.Pool().Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("list tasks: %w", err)
	}
	defer rows.Close()

	var tasks []domain.Task
	for rows.Next() {
		var t domain.Task
		var deadline, completedAt *time.Time
		if err := rows.Scan(&t.ID, &t.Title, &t.Description, &t.CreatorID, &t.CreatorType,
			&t.AssigneeID, &t.ParentTaskID, &t.ChannelID, &t.Status, &t.Priority,
			&deadline, &completedAt, &t.CreatedAt, &t.UpdatedAt); err != nil {
			return nil, fmt.Errorf("scan task: %w", err)
		}
		if deadline != nil && !deadline.IsZero() {
			t.Deadline = deadline
		}
		if completedAt != nil && !completedAt.IsZero() {
			t.CompletedAt = completedAt
		}
		tasks = append(tasks, t)
	}
	if tasks == nil {
		tasks = []domain.Task{}
	}
	return tasks, nil
}

type TaskFilter struct {
	AssigneeID   string
	Status       string
	ChannelID    string
	ParentTaskID *string
	OnlyTopLevel bool // only tasks without parent
}

// UpdateTaskStatus transitions a task to a new status.
func (s *TaskService) UpdateTaskStatus(ctx context.Context, taskID, newStatus string) (*domain.Task, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	now := time.Now()
	var completedAt *time.Time
	if newStatus == "DONE" {
		completedAt = &now
	}

	_, err := s.db.Pool().Exec(ctx, `
		UPDATE tasks SET status=$1, updated_at=$2, completed_at=$3 WHERE id=$4`,
		newStatus, now, completedAt, taskID)
	if err != nil {
		return nil, fmt.Errorf("update task status: %w", err)
	}
	return s.GetTask(ctx, taskID)
}

// AssignTask reassigns a task to a new assignee.
func (s *TaskService) AssignTask(ctx context.Context, taskID, newAssigneeID string) (*domain.Task, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	_, err := s.db.Pool().Exec(ctx, `
		UPDATE tasks SET assignee_id=$1, updated_at=$2 WHERE id=$3`,
		newAssigneeID, time.Now(), taskID)
	if err != nil {
		return nil, fmt.Errorf("assign task: %w", err)
	}
	return s.GetTask(ctx, taskID)
}

// AddSubtask creates a subtask linked to a parent.
func (s *TaskService) AddSubtask(ctx context.Context, parentTaskID, title, description, assigneeID, priority string) (*domain.Task, error) {
	if priority == "" {
		priority = "NORMAL"
	}
	// Get parent to inherit channel
	parent, err := s.GetTask(ctx, parentTaskID)
	if err != nil {
		return nil, fmt.Errorf("parent not found: %w", err)
	}
	req := CreateTaskRequest{
		Title:        title,
		Description:  description,
		CreatorID:    parent.CreatorID,
		CreatorType:  parent.CreatorType,
		AssigneeID:   assigneeID,
		ParentTaskID: &parentTaskID,
		ChannelID:    parent.ChannelID,
		Priority:     priority,
	}
	return s.CreateTask(ctx, req)
}

// GetTaskStats returns Kanban counts grouped by status and assignee.
func (s *TaskService) GetTaskStats(ctx context.Context) (map[string]interface{}, error) {
	if s.db == nil {
		return map[string]interface{}{}, nil
	}
	stats := map[string]interface{}{}

	// Count by status
	rows, err := s.db.Pool().Query(ctx, `SELECT status, count(*) FROM tasks GROUP BY status`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	byStatus := map[string]int{}
	for rows.Next() {
		var s string
		var c int
		rows.Scan(&s, &c)
		byStatus[s] = c
	}
	stats["by_status"] = byStatus

	// Count by assignee
	rows2, err := s.db.Pool().Query(ctx, `SELECT COALESCE(assignee_id::text, 'unassigned'), count(*) FROM tasks GROUP BY assignee_id`)
	if err != nil {
		return nil, err
	}
	defer rows2.Close()
	byAssignee := map[string]int{}
	for rows2.Next() {
		var a string
		var c int
		rows2.Scan(&a, &c)
		byAssignee[a] = c
	}
	stats["by_assignee"] = byAssignee

	return stats, nil
}

// ── Helpers ─────────────────────────────────────────────────────

func nilIfEmpty(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}

func nilIfEmptyP(s *string) interface{} {
	if s == nil || *s == "" {
		return nil
	}
	return *s
}
