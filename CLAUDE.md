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
| 消息 | WebSocket (gorilla/websocket) + gRPC (规划中) |
| LLM | Anthropic SDK (Claude), 可插拔 OpenClaw/Hermes |

## 项目结构

```
Multi-agent-IM/
├── CLAUDE.md                     # 本文件
├── Makefile                      # 根级编排: infra/start-*/test/lint
├── .env.example                  # 环境变量模板
├── docs/                         # 顶层设计文档
│   ├── ARCHITECTURE.md           #   五层架构: Client→Gateway→IM/Agent→Connector→Data
│   ├── AGENT-SOUL.md             #   灵魂系统: Identity/Persona/Values/Memory/Skills
│   ├── ROADMAP.md                #   6阶段路线图
│   ├── INTEGRATION.md            #   AgentConnector 接口 + 多框架适配
│   └── TESTING.md                #   TDD 分层测试策略
├── deploy/
│   ├── docker-compose.dev.yml    #   PostgreSQL+Redis+MinIO 本地环境
│   └── init-scripts/01-init-db.sql  # 9张核心表 + pgvector索引
├── shared/proto/                 # gRPC Proto 定义 (agent/message/task + common)
├── server/
│   ├── im-core/                  #   Go: WebSocket Hub + 消息路由 + 持久化
│   ├── api-gateway/              #   Go: JWT认证 + 反向代理 + 中间件
│   └── agent-runtime/            #   Python: Soul Engine + Reasoning + Claude Connector
├── client/web/                   #   React 飞书风格 UI
├── scripts/                      #   test-all.sh, install-hooks.sh
└── .github/workflows/test.yml    #   CI: Go单测 + Python单测 + 集成测试
```

## 当前阶段: Phase 1 MVP (已完成 2026-06-03)

- [x] JWT 认证 (register/login/me)
- [x] WebSocket 实时消息 (Hub + 频道订阅 + 广播)
- [x] Agent Runtime HTTP API (CRUD + think + 记忆保存)
- [x] Claude API 集成 (Anthropic SDK + tool-use loop + streaming)
- [x] 飞书风格 UI (登录/聊天/Agent管理/私聊/动态排序)
- [x] MD 文档导入 + 任务抢占队列 + 任务级活动状态
- [x] Go + Docker 环境安装 (2026-06-07 已验证)
- [x] 全部 5 个服务联调 (2026-06-07 全链路验证通过)
- [x] 设置 ANTHROPIC_API_KEY (Phase 5: DeepSeek key 已配置，支持5个LLM后端)
- [x] Phase 6 企业级特性 (审计/熔断/RBAC/Webhook/部署, 2026-06-08)

## 开发命令

```bash
# 基础设施
make infra          # 启动 PostgreSQL + Redis + MinIO
make down           # 停止

# 各服务启动 (需要分别在不同终端运行)
make start-im       # IM Core      :8080
make start-gateway  # API Gateway  :3000
make start-agent    # Agent Runtime :50051
make start-web      # React 前端   :5173

# 测试
make test           # 全量测试 (跳过 LLM 调用)
bash scripts/test-all.sh --include-llm  # 含 LLM 调用测试

# 代码检查
make lint           # Go vet + Python ruff + ESLint
```

## 关键设计决策

1. **Agent 走和人类一样的消息管道** — senderType="agent", 天然支持 @提及、表情、引用
2. **灵魂数据独立于大脑后端** — 身份/人格/记忆存自身 DB, 换 LLM 框架不影响人格
3. **proficiency 是仪表盘不是门禁** — 0.1 熟练度的 Agent 也能尝试复杂 SQL, 不被系统阻止
4. **记忆四层分级** — Core(永久) / Working(项目) / Buffer(近期) / Transient(即抛), 每层 Token 配额
5. **人类始终在环路中** — 关键操作需审批, 复盘产生的 Lessons Learned 需人工确认
6. **前端 Dev Mode** — `App.tsx` 中 `DEV_MODE=true` 绕过登录, 方便 UI 开发

## 环境状态 (2026-06-07)

| 组件 | 状态 |
|------|:--:|
| Node.js v20.18.0 | ✓ |
| Python 3.14.5 | ✓ |
| Go 1.26.4 | ✓ (编译通过) |
| Docker 29.5.2 | ✓ |
| PostgreSQL 16 pgvector | ✓ :5432 |
| Redis 7 | ✓ :6379 |
| MinIO | ✓ :9000 |
| 前端 :5173 | ✓ |
| API Gateway :3000 | ✓ |
| IM Core :8080 | ✓ |
| Agent Runtime :50051 | ✓ |
| ANTHROPIC_API_KEY | ✗ 需在 .env 中设置有效 key |

## 下一步 (Phase 2: 多Agent协作)

1. **环境**: 用户安装 Go + Docker → `make infra` 启动全部服务
2. **群组频道**: 多 Agent 在同一频道自主交流
3. **人类旁观/介入**: 人类可查看 Agent 对话并在任意时刻插话
4. **Agent 自主发言**: Agent 基于目标/定时主动发起消息
5. **频道权限**: 人类可设置频道的 Agent 参与权限

## Git

- 仓库: `D:/Projects/Multi-agent-IM`
- 初始提交: `8dada00` — Phase 0 + Phase 1 MVP, 91 files, ~14.7k lines
- 最新提交: `cfd9034` — Phase 6 完成, 15 commits, ~98 files, ~10,500 lines
- 远端: 未配置
