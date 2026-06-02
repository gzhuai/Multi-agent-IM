-- Multi-agent-IM 数据库初始化
-- 在 PostgreSQL 容器首次启动时自动执行

-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 核心表结构 (Phase 0 — 骨架，后续 Phase 逐步完善)
-- ============================================================

-- 组织/租户
CREATE TABLE IF NOT EXISTS organizations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 人类用户
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    username        VARCHAR(100) NOT NULL UNIQUE,
    display_name    VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    password_hash   VARCHAR(255) NOT NULL,
    avatar_url      VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 数字AI员工
CREATE TABLE IF NOT EXISTS agents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name            VARCHAR(100) NOT NULL,
    display_name    VARCHAR(255),
    role            VARCHAR(100),
    department      VARCHAR(100),
    level           INT DEFAULT 1,
    status          VARCHAR(20) NOT NULL DEFAULT 'OFFLINE',
    -- Soul Profile (JSONB — 灵活 schema)
    identity        JSONB DEFAULT '{}',
    persona         JSONB DEFAULT '{}',
    value_system    JSONB DEFAULT '{}',
    cognition       JSONB DEFAULT '{}',
    -- 连接器配置
    connector_type  VARCHAR(50) DEFAULT 'claude_code',
    connector_config JSONB DEFAULT '{}',
    -- 记忆预算 (Token 分配)
    memory_budget   JSONB DEFAULT '{"core": 10000, "working": 20000, "buffer": 10000}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent 记忆条目
CREATE TABLE IF NOT EXISTS agent_memories (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type        VARCHAR(20) NOT NULL CHECK (type IN ('episodic', 'semantic', 'relational')),
    tier        VARCHAR(20) NOT NULL DEFAULT 'buffer' CHECK (tier IN ('core', 'working', 'buffer', 'archived', 'transient')),
    content     JSONB NOT NULL,
    importance  FLOAT NOT NULL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    embedding   vector(1536),          -- pgvector, 维度后续可调
    tags        TEXT[] DEFAULT '{}',
    ttl         INTERVAL,              -- NULL = 永不过期
    project_id  UUID,
    access_count INT DEFAULT 0,
    last_accessed TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 向量索引
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON agent_memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_memories_agent_tier ON agent_memories(agent_id, tier);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON agent_memories(agent_id, importance DESC);

-- Agent 技能
CREATE TABLE IF NOT EXISTS agent_skills (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    proficiency FLOAT NOT NULL DEFAULT 0.0 CHECK (proficiency >= 0 AND proficiency <= 1),
    task_count  INT DEFAULT 0,
    tools       JSONB DEFAULT '[]',
    last_used   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(agent_id, name)
);

-- 已安装的技能包
CREATE TABLE IF NOT EXISTS agent_skill_packs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    pack_name   VARCHAR(200) NOT NULL,
    pack_version VARCHAR(50),
    effects     JSONB DEFAULT '{}',
    installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 频道
CREATE TABLE IF NOT EXISTS channels (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name        VARCHAR(200) NOT NULL,
    type        VARCHAR(20) NOT NULL CHECK (type IN ('direct', 'group', 'department', 'project')),
    is_agent_channel BOOLEAN DEFAULT FALSE,
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 频道成员
CREATE TABLE IF NOT EXISTS channel_members (
    channel_id  UUID NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    member_id   UUID NOT NULL,
    member_type VARCHAR(10) NOT NULL CHECK (member_type IN ('user', 'agent')),
    role        VARCHAR(20) DEFAULT 'member',
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel_id, member_id, member_type)
);

-- 消息 (按月分区)
CREATE TABLE IF NOT EXISTS messages (
    id          UUID NOT NULL DEFAULT uuid_generate_v4(),
    channel_id  UUID NOT NULL REFERENCES channels(id),
    sender_id   UUID NOT NULL,
    sender_type VARCHAR(10) NOT NULL CHECK (sender_type IN ('human', 'agent', 'system')),
    content     JSONB NOT NULL,
    reply_to    UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 创建当前月份分区
CREATE TABLE IF NOT EXISTS messages_2024_06 PARTITION OF messages
    FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');

-- 任务
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    creator_id      UUID NOT NULL,
    creator_type    VARCHAR(10) NOT NULL CHECK (creator_type IN ('human', 'agent')),
    assignee_id     UUID REFERENCES agents(id),
    parent_task_id  UUID REFERENCES tasks(id),
    channel_id      UUID REFERENCES channels(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'TODO' CHECK (status IN ('TODO', 'IN_PROGRESS', 'REVIEW', 'DONE', 'BLOCKED', 'CANCELLED')),
    priority        VARCHAR(10) NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    artifact_urls   TEXT[] DEFAULT '{}',
    deadline        TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 审计日志
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID REFERENCES agents(id),
    action      VARCHAR(100) NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent 演化日志
CREATE TABLE IF NOT EXISTS agent_evolution_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    change_type VARCHAR(50) NOT NULL,
    field_path  VARCHAR(200),
    old_value   JSONB,
    new_value   JSONB,
    source      VARCHAR(50) NOT NULL,  -- 'auto', 'retrospect', 'manual', 'skill_pack'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evolution_agent_time ON agent_evolution_log(agent_id, created_at DESC);
