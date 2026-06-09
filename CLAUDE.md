# CLAUDE.md

> Multi-agent-IM 项目上下文，供 Claude Code 每日继续推进使用。

## 项目概述

即时办公通讯软件。创建数字 AI 员工（兼容 Claude Code / OpenClaw / Hermes），赋予 identity 和 soul，让 AI 在 IM 内即时沟通、处理核心工作，人类可实时观察和介入。

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 18 + TypeScript + TailwindCSS + Zustand + Vite |
| 桌面端 | Electron (规划中) |
| 后端 | Go 1.22 (IM Core + API Gateway) + Python 3.12 (Agent Runtime) |
| 数据库 | PostgreSQL 16 + pgvector + Redis 7 + MinIO |
| 消息 | WebSocket (gorilla/websocket) + REST |
| LLM | 5 providers: Claude, DeepSeek, GPT-4o, Gemini, Groq |

## 项目结构

```
Multi-agent-IM/
├── CLAUDE.md                     # 本文件
├── Makefile                      # 根级编排: infra/start-*/test/lint
├── .env.example                  # 环境变量模板
├── docs/                         # 顶层设计文档
│   ├── TEST-REPORT.html           #   [v2] 完整测试报告（对外展示）
│   ├── ARCHITECTURE.md           #   五层架构: Client→Gateway→IM/Agent→Connector→Data [v2更新]
│   ├── AGENT-SOUL.md             #   灵魂系统: Identity/Persona/Values/Memory/Skills
│   ├── ROADMAP.md                #   6阶段路线图
│   ├── ARCHITECTURE-REFLECTION.md #   [NEW] 架构反思 — AI员工能力本质分析
│   ├── MIGRATION-PLAN.md          #   [NEW] 第二代架构迁移计划 v2
│   ├── PHASE-1-RESEARCH.md        #   [NEW] Phase -1 前置研究报告
│   ├── INTEGRATION.md            #   AgentConnector 接口 + 多框架适配
│   └── TESTING.md                #   TDD 分层测试策略
├── deploy/
│   ├── docker-compose.dev.yml    #   PostgreSQL+Redis+MinIO 本地环境
│   └── init-scripts/01-init-db.sql  # 9张核心表 + pgvector索引
├── shared/proto/                 # gRPC Proto 定义 (agent/message/task + common)
├── server/
│   ├── im-core/                  #   Go: WS Hub + 频道/任务/审计/熔断 + REST API
│   ├── api-gateway/              #   Go: JWT认证 + RBAC + 反向代理
│   └── agent-runtime/            #   Python: SoulEngine + Reasoning + 5 connectors + 记忆/复盘/拆解
├── client/web/                   #   React 飞书风格 UI
├── scripts/                      #   test-all.sh, install-hooks.sh
└── .github/workflows/test.yml    #   CI: Go单测 + Python单测 + 集成测试
```

## 当前阶段: ✅ v2 架构迁移全部完成 (2026-06-10)

> Phase 0-6 + v2 架构升级 7 个 Phase 全部交付。
> 从"内置推理引擎"成功迁移到"外部Agent框架代理"，AI员工现在能真正干活。
>
> 详见:
> - [TEST-REPORT.html](docs/TEST-REPORT.html) — 完整测试报告（对外展示用 HTML）
> - [ARCHITECTURE-REFLECTION.md](docs/ARCHITECTURE-REFLECTION.md) — 为什么需要升级
> - [MIGRATION-PLAN.md](docs/MIGRATION-PLAN.md) — v2 迁移计划
> - [PHASE-1-RESEARCH.md](docs/PHASE-1-RESEARCH.md) — Phase -1 研究结论

### v2 架构迁移 (2026-06-09 ~ 2026-06-10) ✅

| Phase | 内容 | 交付 | 测试 |
|:-----:|:-----|:-----|:----:|
| **-1** | 前置研究 — 验证 Anthropic/OpenClaw/Hermes 可用性 | PHASE-1-RESEARCH.md | 研究 |
| **0** | 接口冻结 — AgentConnectorV2/SoulSerializer/EventBus/Sandbox | 6 new files | — |
| **1** | 双轨运行 — ConnectorRouter v1/v2 分发 | 1 module | 24 |
| **2** | Anthropic Agent Connector — 12工具·双后端(Anthropic+DeepSeek) | anthropic_agent.py | 25 |
| **3** | WorkflowEngine — DAG编排·拓扑分层·并行分发 | workflow_engine.py | 20 |
| **4** | Hermes Agent Connector — NousResearch AIAgent 集成 | hermes_agent.py | 14 |
| **5** | UI改造 — 框架选择/AgentEventStream/ApprovalCard | 4 components | — |
| **5+** | Claude Code CLI Connector — 子进程集成完整 Claude Code harness | claude_code_cli.py | ✅ 实测 |

> **总计**: 33 文件 (19 新增 + 14 修改) | 160 tests | 0 回归 | 4 个 v2 Connector 全部就绪

### Phase 0-1 MVP ✅
- [x] JWT 认证 (register/login/me)
- [x] WebSocket 实时消息 (Hub + 频道订阅 + 广播)
- [x] Agent Runtime HTTP API (CRUD + think + 记忆保存)
- [x] Claude API 集成 + 飞书风格 UI

### Phase 2 多Agent协作 ✅
- [x] 群组频道 (创建/加入/成员管理)
- [x] 多Agent在同一频道各自推理回复 (并行 goroutine)
- [x] Agent消息不触发其他Agent (防死循环)
- [x] Agent 自主发言 (AutonomyManager, 定时唤醒)
- [x] 人类旁观模式 (observer role, 只读WebSocket)
- [x] 频道级暂停/恢复 (POST /api/channels/pause|resume)
- [x] 频道创建 UI (ChannelCreateDialog)

### Phase 3 任务与工作流 ✅
- [x] 任务 CRUD (task_service + task_handler)
- [x] 多条件筛选 (assignee/status/channel/top_level)
- [x] 状态流转 (TODO→IN_PROGRESS→REVIEW→DONE)
- [x] LLM 任务拆解 (task_decomposer.py, 1→4子任务)
- [x] Kanban 看板 (TasksPage.tsx, 4列+详情弹窗)
- [x] 任务统计 (/api/tasks/stats)

### Phase 4 灵魂系统深化 ✅
- [x] LLM 重要性评估 (替代硬编码 keyword 匹配)
- [x] 语义记忆搜索 (embedding + pgvector cosine)
- [x] 记忆管理 API (浏览/搜索/promote/archive)
- [x] 人格驱动行为差异 (12个 render 函数, OCEAN→具体指令)
- [x] Agent 自我复盘 (retrospect.py, 五步法)
- [x] Soul 雷达图 (SoulRadar.tsx, 六维 SVG)
- [x] 记忆面板 (MemoryPanel.tsx, 搜索/管理)

### Phase 5 多框架兼容 ✅
- [x] 5 LLM providers (DeepSeek/GPT-4o/Claude/Gemini/Groq + 自定义)
- [x] Per-agent LLM 隔离 (Agent DB 配置 > 环境变量)
- [x] 性能追踪 (MetricsTracker, 延迟/token/错误率)
- [x] 框架对比仪表盘 (FrameworkCompare.tsx)
- [x] Agent 创建时选择 LLM 后端 (前端6选1)

### Phase 6 企业级特性 ✅
- [x] 审计日志 (audit_service + AuditLogViewer)
- [x] 紧急熔断 (pause-all / resume-all, EmergencyPanel)
- [x] RBAC (JWT role + RequireRole中间件, admin/member/viewer)
- [x] Slack Webhook (POST /api/webhooks/slack)
- [x] 消息导出 Markdown (GET /api/export/chat/{id}?format=md)
- [x] 生产部署 (docker-compose.prod.yml + nginx.conf + deploy.sh)

## 开发命令

```bash
# 基础设施
docker compose -f deploy/docker-compose.dev.yml up -d   # PG+Redis+MinIO
docker compose -f deploy/docker-compose.dev.yml down    # 停止

# 各服务启动 (4个终端)
cd server/im-core && go run ./cmd/server/main.go        # IM Core      :8080
cd server/api-gateway && go run ./cmd/server/main.go     # API Gateway  :3000
cd server/agent-runtime && python -m agent_runtime.app   # Agent RT     :50051
cd client/web && npm run dev                              # 前端         :5173

# 测试
cd server/im-core && go test ./internal/... -short -count=1
cd server/agent-runtime && python -m pytest tests/ -x -q --timeout=10
cd server/api-gateway && go vet ./...

# 生产部署
bash scripts/deploy.sh
```

## 关键设计决策

1. **Agent 走和人类一样的消息管道** — senderType="agent", 天然支持 @提及
2. **灵魂数据独立于大脑后端** — 身份/人格/记忆存自身 DB, 换 LLM 框架不影响人格
3. **proficiency 是仪表盘不是门禁** — 0.1 熟练度也能尝试复杂操作, 不被系统阻止
4. **记忆四层分级** — Core(永久) / Working(项目) / Buffer(近期) / Transient(即抛)
5. **人类始终在环路中** — 关键操作需审批, 复盘 Lessons Learned 需人工确认
6. **前端 DEV_MODE=true** — 绕过登录方便开发
7. **扁平化组织** — 不设部门/团队层级, Agent 自由协作, 后期按需拖拽分组
8. **Per-agent LLM 隔离** — Agent DB 配置优先于环境变量, 每个Agent独立后端
9. **Agent 不互触发** — sender_type!=agent 的消息才触发频道内Agent, 防死循环
10. **Per-framework 独立** — 每个 Agent 指定大脑框架(Anthropic/Hermes/WorkflowEngine)，各展所长 (v2)
11. **双后端自动检测** — AnthropicAgentConnector 自动识别 Anthropic/DeepSeek/OpenAI API key，无需手动切换 (v2)
12. **事件驱动架构** — Agent 执行过程通过 EventBus 实时推送状态（THINKING→TOOL_EXEC→APPROVAL→DONE）(v2)
13. **沙箱隔离** — 文件/Shell 操作在沙箱内执行，危险命令自动拦截 (v2)

## 环境状态 (2026-06-10) — 全栈已启动

| 组件 | 状态 |
|------|:--:|
| Node.js v20.18.0 | ✓ |
| Python 3.14.5 | ✓ |
| Go 1.26.4 | ✓ |
| Docker 29.5.2 | ✓ |
| PostgreSQL 16 pgvector | ✓ :5432 |
| Redis 7 | ✓ :6379 |
| MinIO | ✓ :9000 |
| 前端 :5173 | ✓ |
| API Gateway :3000 | ✓ |
| IM Core :8080 | ✓ |
| Agent Runtime :50051 | ✓ (3 v2 Connector 已注册) |
| DeepSeek API | ✓ (sk-xxx... 已配置) |
| ANTHROPIC_API_KEY | ✗ (可用但未配置真实 key — placeholder) |

### v2 Connector 注册状态
```
CONNECTOR_REGISTRY_V2 = {
  'anthropic_agent':  AnthropicAgentConnector   # SDK 直连 (Anthropic+DeepSeek 双后端)
  'claude_code_cli':  ClaudeCodeCLIConnector    # CLI 子进程 (完整 Claude Code harness)
  'hermes_agent':     HermesAgentConnector      # NousResearch AIAgent 集成
  'workflow_engine':  WorkflowEngine            # DAG 编排引擎
}
```

## 待办

### v2 收尾
- [ ] Go 换为 amd64 版本 (当前 386)
- [ ] 编写 Go 服务生产 Dockerfile
- [ ] cloudflared/cpolar 公网隧道

### 文档
- [x] PHASE-1-RESEARCH.md — 前置研究
- [x] ARCHITECTURE-REFLECTION.md — 架构反思
- [x] MIGRATION-PLAN.md — v2 迁移计划
- [x] TEST-REPORT.html — 测试报告

## Git

- 仓库: `D:/Projects/Multi-agent-IM`
- 远端: https://github.com/gzhuai/Multi-agent-IM
- 最新提交: `16b41bb` — feat: Claude Code CLI Connector
- v2 总提交: 2 个 (v2 架构升级 + Claude Code CLI)
- v2 新增: ~6,000 lines

---

## 明日继续入口 (2026-06-10 收工状态)

### 当前状态
- **160 tests, 0 fail** — 全绿
- **4 个 v2 Connector 全部就绪** — anthropic_agent / claude_code_cli / hermes_agent / workflow_engine
- **DeepSeek API 已验证** — 用你已有的 key 就能让 AI 员工干活
- **Claude Code CLI 已验证** — 通过子进程调用，完整 harness 可用
- **GitHub push 待重试** — commit 已本地保存 (`16b41bb`)，网络恢复后 `git push`

### 启动命令（明天继续时）
```bash
docker compose -f deploy/docker-compose.dev.yml up -d
cd server/im-core && go run ./cmd/server/main.go &
cd server/api-gateway && go run ./cmd/server/main.go &
cd server/agent-runtime && python -m agent_runtime.app &
cd client/web && npm run dev &
# 前端: http://localhost:5173
```

### 建议下一步
1. **git push** — 网络恢复后推送到 GitHub
2. **OpenClaw ACP Connector** — 如果你装了 OpenClaw，可以参照 claude_code_cli.py 模式新增
3. **在线体验** — 打开 http://localhost:5173，创建 Agent，在频道里对话
4. **配置 Anthropic API key** — 把 `.env` 里的 `ANTHROPIC_API_KEY=your-anthropic-api-key-here` 换成真实 key
5. **修复 7 个前端 TS 错误** — 都是预先存在的，非 v2 引入
6. **Go amd64 + 生产 Dockerfile** — 基础设施收尾
