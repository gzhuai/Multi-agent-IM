-- ============================================================
-- Multi-agent-IM v2 架构迁移 — 数据库变更
-- Phase 1 执行: 瘦身 Agent Runtime + 双轨运行
-- ============================================================
-- 注意: 所有变更都是累加的（ADD COLUMN, CREATE TABLE），
--        不删除任何现有表/列，保证旧路径 Agent 不受影响。
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. agents 表 — 新增 v2 字段
-- ────────────────────────────────────────────────────────────

-- v2 框架标识符 (anthropic_agent | hermes_agent | workflow_engine)
-- 区分于旧版 connector_type (claude_code | openai_compatible)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS connector_type_v2 VARCHAR(50);

-- 工具权限白名单 (默认只有发送消息和创建任务的权限)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS tool_permissions JSONB DEFAULT '["send_message", "create_task"]';

-- 沙箱配置 (每个 Agent 可自定义沙箱参数)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS sandbox_config JSONB DEFAULT '{}';

-- 审批策略覆盖 (每个 Agent 可自定义哪些操作需要审批)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS approval_overrides JSONB DEFAULT '{}';

-- ────────────────────────────────────────────────────────────
-- 2. tool_executions 表 — 工具调用执行记录
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tool_executions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task_id         UUID,                          -- 关联的任务 ID
    connector_type  VARCHAR(50) NOT NULL,          -- 哪个框架执行的
    tool_name       VARCHAR(100) NOT NULL,         -- 工具名
    tool_params     JSONB,                          -- 参数（已脱敏）
    tool_result     JSONB,                          -- 结果摘要
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    sandbox_id      VARCHAR(100),                   -- 沙箱容器 ID
    approval_id     UUID,                           -- 关联的审批记录
    risk_level      VARCHAR(20) NOT NULL DEFAULT 'SAFE',
    duration_ms     FLOAT,
    exit_code       INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_exec_agent_time ON tool_executions(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_exec_task ON tool_executions(task_id);
CREATE INDEX IF NOT EXISTS idx_tool_exec_connector ON tool_executions(connector_type);

-- ────────────────────────────────────────────────────────────
-- 3. approvals 表 — 人类审批记录
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS approvals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    channel_id      UUID REFERENCES channels(id),   -- 发起审批的频道
    task_id         UUID,                            -- 关联的任务
    connector_type  VARCHAR(50) NOT NULL,
    tool_name       VARCHAR(100) NOT NULL,           -- 哪个工具触发审批
    action_description TEXT,                         -- 操作描述（人类可读）
    action_detail   JSONB,                           -- 操作详情（参数摘要）
    risk_level      VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        -- PENDING | APPROVED | DENIED | TIMEOUT | CANCELLED
    approved_by     UUID REFERENCES users(id),      -- 审批人
    comment         TEXT,                            -- 审批意见
    timeout_at      TIMESTAMPTZ,                     -- 超时时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_approvals_agent ON approvals(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_channel ON approvals(channel_id);

-- ────────────────────────────────────────────────────────────
-- 4. audit_logs 表 — 扩展字段
-- ────────────────────────────────────────────────────────────

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS connector_type VARCHAR(50);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS tool_execution_id UUID;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS sandbox_id VARCHAR(100);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS approval_id UUID;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS task_id UUID;

-- ────────────────────────────────────────────────────────────
-- 5. agent_sessions 表 — Agent 执行会话（NEW）
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    channel_id      UUID REFERENCES channels(id),
    task_id         UUID,
    connector_type  VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'STARTED',
        -- STARTED | THINKING | EXECUTING | AWAITING_APPROVAL | DONE | ERROR | CANCELLED
    model           VARCHAR(100),                    -- 使用的模型
    sandbox_id      VARCHAR(100),
    tokens_in       INT DEFAULT 0,
    tokens_out      INT DEFAULT 0,
    rounds          INT DEFAULT 0,                    -- agent loop 轮次
    duration_ms     FLOAT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent ON agent_sessions(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_channel ON agent_sessions(channel_id);

-- ────────────────────────────────────────────────────────────
-- 6. 给现有 Agent 的默认数据迁移
-- ────────────────────────────────────────────────────────────

-- 将现有 connector_type='claude_code' 映射到 v2 的 'anthropic_agent'
-- (仅在 connector_type_v2 为空时设置，保留手动设置的值)
UPDATE agents
SET connector_type_v2 = CASE
    WHEN connector_type = 'claude_code' THEN 'anthropic_agent'
    WHEN connector_type = 'openai_compatible' THEN 'anthropic_agent'  -- 默认走 Anthropic
    ELSE 'anthropic_agent'
END
WHERE connector_type_v2 IS NULL;

-- 为现有 Agent 设置默认工具权限（保有旧行为: send_message + create_task）
UPDATE agents
SET tool_permissions = '["send_message", "create_task"]'
WHERE tool_permissions IS NULL OR tool_permissions = '{}';

-- 为现有 Agent 设置默认沙箱配置
UPDATE agents
SET sandbox_config = '{"mode": "local", "max_runtime_s": 600, "cpu_limit": "2.0", "memory_limit": "2g"}'
WHERE sandbox_config IS NULL OR sandbox_config = '{}';
