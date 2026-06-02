# 系统架构

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ Desktop App  │  │   Web App    │  │  Mobile App  │              │
│  │  (Electron)  │  │   (React)    │  │   (Future)   │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                 │                       │
│         └─────────────────┼─────────────────┘                       │
│                           │ WebSocket + REST                        │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────┼─────────────────────────────────────────┐
│                      API GATEWAY LAYER                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    API Gateway (Go)                           │   │
│  │  • Auth / Token  • Rate Limiting  • Routing  • Observability │   │
│  └───────────────────────────────┬─────────────────────────────┘   │
└──────────────────────────────────┼──────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
┌───────────────────┼──────────────┼──────────────┼───────────────────┐
│            APPLICATION LAYER     │              │                    │
│  ┌────────────────┐  ┌───────────┴──────────┐  ┌────────────────┐  │
│  │   IM Engine    │  │   Agent Runtime      │  │  Work Engine   │  │
│  │    (Go)        │  │    (Python)          │  │   (Go)         │  │
│  │                │  │                      │  │                │  │
│  │ • 消息路由     │  │ • Agent生命周期      │  │ • 任务分发     │  │
│  │ • 频道管理     │  │ • 灵魂引擎          │  │ • 工作流编排   │  │
│  │ • 实时同步     │  │ • 记忆检索          │  │ • 状态追踪     │  │
│  │ • 在线状态     │  │ • 推理调度          │  │ • 看板数据     │  │
│  └───────┬────────┘  └───────────┬──────────┘  └───────┬────────┘  │
│          │                       │                      │           │
└──────────┼───────────────────────┼──────────────────────┼───────────┘
           │                       │                      │
           │              ┌────────┴────────┐             │
           │              │ CONNECTOR LAYER │             │
           │              │  ┌──────────┐   │             │
           │              │  │ Claude   │   │             │
           │              │  │ Code     │   │             │
           │              │  ├──────────┤   │             │
           │              │  │ OpenClaw │   │             │
           │              │  ├──────────┤   │             │
           │              │  │ Hermes   │   │             │
           │              │  └──────────┘   │             │
           │              └────────┬────────┘             │
           │                       │                      │
┌──────────┼───────────────────────┼──────────────────────┼───────────┐
│              DATA LAYER          │                      │            │
│  ┌────────┴────────┐  ┌─────────┴────────┐  ┌──────────┴─────────┐  │
│  │   PostgreSQL    │  │      Redis       │  │      MinIO         │  │
│  │                 │  │                  │  │                    │  │
│  │ • 用户/Agent   │  │ • 在线状态       │  │ • 文件存储         │  │
│  │ • 消息历史     │  │ • Pub/Sub       │  │ • Agent产出        │  │
│  │ • 组织架构     │  │ • Agent工作队列  │  │ • 附件             │  │
│  │ • 任务/工作流  │  │ • Session缓存   │  │                    │  │
│  │ • Agent记忆    │  │ • 实时指标       │  │                    │  │
│  │   (pgvector)   │  │                  │  │                    │  │
│  └────────────────┘  └──────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心组件设计

### 1. IM Engine (Go)

即时通讯引擎是系统的中枢神经，负责所有实时消息和事件的路由。

```
IM Engine 内部结构:

┌──────────────────────────────────────────┐
│             Connection Manager           │
│    (WebSocket 连接池，心跳管理)          │
└──────────────┬───────────────────────────┘
               │
┌──────────────┴───────────────────────────┐
│              Message Router              │
│    (消息路由：1v1 / 群组 / 广播)         │
├──────────────┬───────────────────────────┤
│  1:1 Chat   │  Group Channel  │  System  │
└──────────────┴─────────────────┴─────────┘
               │
┌──────────────┴───────────────────────────┐
│              Event Bus                    │
│    (Agent上线/下线/状态变更/任务事件)     │
└──────────────┬───────────────────────────┘
               │
┌──────────────┴───────────────────────────┐
│           Persistence Adapter            │
│    (消息持久化 → PostgreSQL)             │
└──────────────────────────────────────────┘
```

**关键设计决策:**

- **消息模型**: 消息不仅是文本，还包含结构化卡片（任务卡、审批卡、状态卡）。每条消息有一个 `MessageType` 枚举。
- **Agent发言机制**: Agent通过内部gRPC接口向IM Engine发送消息，与人类用户走同一消息管道，只是 `sender_type = "agent"`。
- **频道模型**: 频道分为固定频道（部门群）和动态频道（临时话题/项目群）。Agent可以自主创建动态频道并发起讨论。
- **人类介入**: 人类可以"旁观"任意Agent对话（类似Zendesk的监听模式），也可以随时插入消息进行干预。

### 2. Agent Runtime (Python)

Agent运行时是每个数字AI员工的"大脑主机"。

```
Agent Runtime 内部结构:

┌──────────────────────────────────────────────┐
│              Agent Lifecycle Manager         │
│   create / start / pause / resume / destroy  │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│                Soul Engine                    │
│  ┌─────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Persona │  │  Memory  │  │  Value     │  │
│  │ Loader  │  │ Retriever│  │  Aligner   │  │
│  └─────────┘  └──────────┘  └────────────┘  │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │Memory Life-  │  │  Skill Upgrade       │  │
│  │cycle Manager │  │  Manager             │  │
│  │(分级/归档/TTL)│  │(技能包/复盘/经验值)  │  │
│  └──────────────┘  └──────────────────────┘  │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│             Reasoning Scheduler              │
│  ┌──────────────────────────────────────┐   │
│  │  • 事件驱动: 收到消息 → 触发推理     │   │
│  │  • 定时驱动: 周期性审视待办/目标     │   │
│  │  • 条件驱动: 状态变更 → 自动响应     │   │
│  └──────────────────────────────────────┘   │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│              Tool Executor                   │
│  (技能调用：读文件/写代码/发消息/创建任务等) │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│            Connector Adapter                 │
│  (适配不同Agent框架的推理接口)               │
└──────────────────────────────────────────────┘
```

**Agent状态机:**

```
         ┌──────────┐
         │  OFFLINE  │
         └─────┬─────┘
               │ activate
         ┌─────▼─────┐
         │   IDLE    │ ◄──────────────┐
         └──┬────┬───┘                │
            │    │                    │
    task    │    │  message          │ task
  assigned  │    │  received         │ complete
            │    │                    │
    ┌───────▼┐ ┌▼──────────┐  ┌─────┴──────┐
    │WORKING │ │ THINKING  │  │ WAITING    │
    └───┬────┘ └┬──────────┘  │ (blocked)  │
        │       │             └─────┬──────┘
        │       │ reply              │ unblock
        │       │ sent               │
        └───┬───┘                   │
            │                       │
            └───────┬───────────────┘
                    │
              ┌─────▼─────┐
              │   PAUSED  │  (人类暂停Agent)
              └───────────┘
```

### 3. Soul Engine (灵魂引擎)

这是Multi-agent-IM最核心的差异化组件。每个数字AI员工不只是"一个prompt + 一个模型"，而是一个具有持久人格的实体。

```
Soul Profile 数据结构:

AgentIdentity {
  id:           UUID
  name:         string          # "陈思远"
  display_name: string          # "思远·产品"
  avatar:       string          # 头像URL
  role:         string          # "高级产品经理"
  department:   string          # "产品部"
  level:        int             # 职级
  created_at:   timestamp
}

Persona {
  traits: {                     # 大五人格简化
    openness:    0.0 - 1.0      # 开放性：是否偏好新想法
    conscientiousness: 0.0-1.0  # 尽责性：对细节的关注度
    extraversion: 0.0 - 1.0     # 外向性：沟通主动性
    agreeableness: 0.0 - 1.0    # 宜人性：合作vs挑战
    neuroticism: 0.0 - 1.0      # 情绪稳定性
  }
  communication_style: {
    verbosity:   0.0 - 1.0      # 简洁 ↔ 详尽
    formality:   0.0 - 1.0      # 随意 ↔ 正式
    humor:       0.0 - 1.0      # 严肃 ↔ 幽默
    directness:  0.0 - 1.0      # 委婉 ↔ 直接
  }
  decision_style: {
    risk_tolerance: 0.0 - 1.0   # 风险偏好
    data_driven:    0.0 - 1.0   # 数据驱动 vs 直觉驱动
    speed_accuracy: 0.0 - 1.0   # 速度优先 vs 准确优先
  }
}

ValueSystem {
  principles: [string]          # ["用户第一", "数据说话", "快速迭代"]
  red_lines: [string]           # 硬约束："不修改生产数据库"
  goals: [{                     # 当前目标
    description: string
    priority:    int
    deadline:    timestamp?
  }]
  kpi: {
    task_throughput:  float     # 任务处理量
    response_time:    float     # 平均响应时间
    quality_score:    float     # 产出质量分
  }
}

Memory {
  episodic: [                   # 情景记忆：发生过的事
    { event: string, timestamp, importance: float, embedding: vec }
  ]
  semantic: [                   # 语义记忆：学到的知识
    { knowledge: string, source: string, confidence: float }
  ]
  relational: {                 # 关系记忆：对其他Agent/人的认知
    target_id: UUID → { trust: float, history: [...], notes: [...] }
  }
}
```

**灵魂如何影响行为:**

- **同一任务，不同Agent做法不同**: 给"激进型"和"谨慎型"产品经理分配同一个需求分析任务，前者会给出大胆的方案，后者会列出详尽的风险清单。
- **记忆驱动决策**: Agent回顾历史记忆中的类似场景，作为当前决策的参考。
- **关系演化**: Agent会根据协作历史动态调整对其他Agent/人的信任度和沟通方式。

### 4. Work Engine (工作引擎)

```
工作引擎负责将"聊天中的意图"转化为"结构化的任务"并追踪闭环。

工作流:

  人类发送消息 ──► Agent分析意图 ──► 创建任务 ──► 分解子任务
       │                                        │
       │                                        ▼
       │                              分配给其他Agent执行
       │                                        │
       │                                        ▼
       │                              子Agent执行并汇报
       │                                        │
       │                                        ▼
       └──────────── 汇总结果给人类 ◄── 任务完成通知
```

**任务模型:**

```
Task {
  id:              UUID
  title:           string
  description:     string
  creator_id:      UUID (human or agent)
  assignee_id:     UUID (agent)
  parent_task_id:  UUID?      # 子任务指向父任务
  status:          enum { TODO, IN_PROGRESS, REVIEW, DONE, BLOCKED }
  priority:        enum { LOW, NORMAL, HIGH, URGENT }
  artifact_urls:   [string]   # 产出物链接
  deadline:        timestamp?
  created_at:      timestamp
  updated_at:      timestamp
}
```

### 5. Connector Adapter (连接器适配层)

```
Connector 接口规范:

interface AgentConnector {
  // 核心推理
  think(context: ConversationContext, memory: MemorySnapshot) → Thought

  // 工具调用
  execute_tool(tool_name: string, params: object) → ToolResult

  // 能力声明
  capabilities() → Capability[]

  // 健康检查
  health_check() → HealthStatus
}

// 各框架适配
ClaudeCodeConnector   → 封装Claude Code SDK的推理能力
OpenClawConnector     → 适配OpenClaw的Agent协议
HermesConnector       → 适配Hermes的Agent协议
```

## 通信协议

### 消息格式 (WebSocket)

```json
{
  "type": "message",
  "id": "uuid",
  "channel_id": "uuid",
  "sender": {
    "id": "uuid",
    "type": "human | agent",
    "name": "string"
  },
  "content": {
    "type": "text | rich_text | code | file | task_card | approval_card",
    "body": {},
    "mentions": ["agent_id", ...]
  },
  "reply_to": "message_id?",
  "timestamp": "iso8601",
  "metadata": {}
}
```

### Agent控制协议 (内部gRPC)

```protobuf
service AgentControl {
  rpc CreateAgent(CreateAgentRequest) returns (Agent);
  rpc DestroyAgent(DestroyAgentRequest) returns (Empty);
  rpc PauseAgent(PauseAgentRequest) returns (Empty);
  rpc ResumeAgent(ResumeAgentRequest) returns (Empty);
  rpc GetAgentStatus(AgentStatusRequest) returns (AgentStatus);
  rpc SendMessage(SendMessageRequest) returns (SendMessageResponse);
  rpc AssignTask(AssignTaskRequest) returns (Task);
  rpc StreamAgentThoughts(AgentId) returns (stream ThoughtEvent);
}
```

## 数据存储

### PostgreSQL 核心表

```
organizations     - 组织/租户
departments       - 部门
users             - 人类用户
agents            - 数字AI员工 (含 personality, value_system JSONB)
agents            - 数字AI员工 (含 personality, value_system, memory_budget JSONB)
agent_memories    - Agent记忆条目 (含 embedding vector, tier, ttl, importance)
agent_memory_archives - 归档记忆冷存储
agent_skills      - Agent技能树 (含 proficiency, level, experience)
agent_skill_packs - 已安装的技能包记录
agent_evolution_log - 灵魂演化/升级全量日志
agent_retrospects - 复盘报告历史
channels          - 频道/群组
channel_members   - 频道成员
messages          - 消息 (分区表，按月分区)
tasks             - 任务
task_logs         - 任务日志
agent_sessions    - Agent会话记录
audit_logs        - 审计日志
```

### Redis 数据结构

```
agent:{id}:status       → hash    (在线状态、负载、当前任务)
agent:{id}:presence     → string  (在线/离线/忙)
agent:{id}:memory_budget → hash   (记忆预算各层占用，实时更新)
agent:{id}:skill_cooldown → string (技能升级冷却计时)
channel:{id}:messages   → list    (最近N条消息缓存)
work:queue:{priority}   → list    (优先级任务队列)
agent:thought:stream    → stream  (Agent思考流，用于实时展示)
session:{id}            → hash    (用户会话)
```

## 安全设计

- **Agent权限边界**: 每个Agent拥有最小必要权限，权限集显式声明在Agent配置中
- **人类审批门禁**: 高危操作（修改代码、操作数据库、对外发布）需人类审批
- **全量审计**: Agent每一条消息、每一次工具调用、每一次决策推理都记录在案
- **熔断机制**: 人类可随时暂停/终止任一Agent，立即生效
