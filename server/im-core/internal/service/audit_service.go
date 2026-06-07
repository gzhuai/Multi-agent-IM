package service

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/multi-agent-im/im-core/internal/repository"
)

// AuditService writes and queries audit log entries.
type AuditService struct {
	db *repository.PostgresStore
}

func NewAuditService(db *repository.PostgresStore) *AuditService {
	return &AuditService{db: db}
}

// LogAction inserts an audit record. Safe to call from any goroutine.
func (s *AuditService) LogAction(ctx context.Context, agentID, action string, detail map[string]interface{}) error {
	if s.db == nil {
		return nil // silent no-op
	}
	id := uuid.New().String()
	detailJSON, _ := json.Marshal(detail)
	_, err := s.db.Pool().Exec(ctx,
		`INSERT INTO audit_logs (id, agent_id, action, detail, created_at)
		 VALUES ($1, $2, $3, $4::jsonb, $5)`,
		id, agentID, action, string(detailJSON), time.Now(),
	)
	return err
}

// LogActionSimple logs an audit event with a string detail.
func (s *AuditService) LogActionSimple(ctx context.Context, agentID, action, detail string) {
	s.LogAction(ctx, agentID, action, map[string]interface{}{"detail": detail})
}

// AuditFilter narrows audit log queries.
type AuditFilter struct {
	AgentID string
	Action  string
	Since   string // ISO timestamp
	Limit   int
}

// QueryAuditLogs returns audit records matching the filter.
func (s *AuditService) QueryAuditLogs(ctx context.Context, f AuditFilter) ([]map[string]interface{}, error) {
	if s.db == nil {
		return nil, fmt.Errorf("database not available")
	}
	q := `SELECT id, agent_id, action, detail, created_at FROM audit_logs WHERE 1=1`
	args := []interface{}{}
	argIdx := 1

	if f.AgentID != "" {
		q += fmt.Sprintf(" AND agent_id = $%d", argIdx)
		args = append(args, f.AgentID)
		argIdx++
	}
	if f.Action != "" {
		q += fmt.Sprintf(" AND action = $%d", argIdx)
		args = append(args, f.Action)
		argIdx++
	}
	if f.Since != "" {
		q += fmt.Sprintf(" AND created_at >= $%d", argIdx)
		args = append(args, f.Since)
		argIdx++
	}
	q += " ORDER BY created_at DESC"
	if f.Limit > 0 {
		q += fmt.Sprintf(" LIMIT %d", f.Limit)
	} else {
		q += " LIMIT 100"
	}

	rows, err := s.db.Pool().Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var logs []map[string]interface{}
	for rows.Next() {
		var id, agentID, action, detail string
		var ts time.Time
		rows.Scan(&id, &agentID, &action, &detail, &ts)
		logs = append(logs, map[string]interface{}{
			"id": id, "agent_id": agentID, "action": action,
			"detail": detail, "created_at": ts.Format(time.RFC3339),
		})
	}
	if logs == nil {
		logs = []map[string]interface{}{}
	}
	return logs, nil
}

// AuditStats returns action counts and daily activity.
func (s *AuditService) AuditStats(ctx context.Context) (map[string]interface{}, error) {
	if s.db == nil {
		return map[string]interface{}{}, nil
	}
	// By action
	rows, _ := s.db.Pool().Query(ctx, `SELECT action, count(*) FROM audit_logs GROUP BY action ORDER BY count DESC LIMIT 20`)
	defer rows.Close()
	byAction := map[string]int{}
	for rows.Next() {
		var a string
		var c int
		rows.Scan(&a, &c)
		byAction[a] = c
	}
	// Total
	var total int
	s.db.Pool().QueryRow(ctx, `SELECT count(*) FROM audit_logs`).Scan(&total)
	// Today
	var today int
	s.db.Pool().QueryRow(ctx, `SELECT count(*) FROM audit_logs WHERE created_at >= CURRENT_DATE`).Scan(&today)

	return map[string]interface{}{
		"total": total, "today": today, "by_action": byAction,
	}, nil
}
