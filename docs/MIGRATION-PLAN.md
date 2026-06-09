# 第二代架构迁移计划 v2

> 从"内置推理引擎"到"外部框架代理"的演进路线
> 规划日期：2026-06-09 | v2 升级：2026-06-09 | Phase -1 完成：2026-06-09
> 预计工期：6~8周

---

## 版本说明

v1 → v2 变更摘要：

| 变更 | 原因 |
|:-----|:-----|
| Phase 顺序重排 | 先定义接口再实现，避免 Connector 紧耦合旧 Runtime |
| 新增 Phase -1: 前置研究 | ✅ **已完成** — 见 [PHASE-1-RESEARCH.md](PHASE-1-RESEARCH.md) |
| "Claude Code Connector" → "Anthropic Agent Connector" | 消除歧义——我们用的是 Anthropic API + 自主工具循环，不是 Claude Code CLI |
| **Phase 3 OpenClaw → WorkflowEngine** | 🔄 OpenClaw 是竞品平台，非嵌入式框架；改为自建轻量 DAG 编排 |
| Phase 4 Hermes Connector 工期 +2天 | Hermes AIAgent 是同步 API，需异步桥接 |
| 新增 **安全架构** 章节 | 沙箱隔离、权限模型、审计链路 |
| 新增 **事件驱动架构** 章节 | 外部 Agent 可能执行数分钟，不能阻塞 HTTP 请求 |
| 新增 **双轨运行策略** | 渐进迁移，旧 Agent 不受影响 |

---

## 一、现状：第一代架构

```
Python Agent Runtime (monolithic — "大脑")
  ├─ ReasoningEngine   (自己做推理、prompt组装、工具循环)
  ├─ SoulEngine        (人格渲染 ✓)
  ├─ MemoryEngine      (记忆管理 ✓)
  ├─ Connector         (只是调 LLM API 拿文本)
  └─ ToolExecutor      (只有 send_message + create_task)

AI员工 = 会说话有性格的聊天机器人
        能做的事：产生文字回复
        不能做的事：读写文件、执行命令、Git操作、多步规划、真实工作
```

## 二、目标：第二代架构

```
Agent Runtime（轻量调度层 — "神经系统"）
  ├─ ConnectorRouter    (按 agent.connector_type 分发)
  ├─ SoulSerializer     (SoulProfile → 各框架格式)
  ├─ MemoryService      (统一记忆 CRUD + 语义搜索)
  ├─ EventBus           (NEW: 异步事件通知)
  ├─ SandboxManager     (NEW: 沙箱隔离)
  └─ LifecycleManager   (状态机: IDLE→THINKING→WORKING→...)
       │
       │ Router 根据 agent.connector_type 分发到不同"大脑"
       │
  ┌────┼────────┬───────────┐
  │    │        │           │
  ▼    ▼        ▼           ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│Anth- │ │Open- │ │Her-  │ │未来  │
│ropic │ │Claw  │ │mes   │ │框架  │
│Agent │ │      │ │      │ │      │
│———   │ │———   │ │———   │ │———   │
│文件IO │ │多Agent│ │结构化 │ │...   │
│Shell  │ │工作流 │ │输出   │ │      │
│Git    │ │DAG   │ │多步   │ │      │
│搜索   │ │调度  │ │规划   │ │      │
│调试   │ │      │ │分支   │ │      │
└──────┘ └──────┘ └──────┘ └──────┘

AI员工 = 有灵魂、有记忆、能干实事的数字员工
```

**关键认识**：我们不是"再写一个Agent框架"。我们是做一个**中立平台**——灵魂和记忆由平台管，干活的能力委托给各自最擅长的框架。

---

## 三、架构原则（含新增）

| 原则 | 含义 | v2 新增? |
|:-----|:-----|:--------|
| **灵魂与大脑分离** | Soul Profile 由 Agent Runtime 管理，注入各框架作为 context | — |
| **记忆统一存储** | 所有 Agent 记忆集中于 PostgreSQL+pgvector，框架通过 Runtime API 访问 | — |
| **消息管道不变** | IM Core WebSocket 机制不动，Agent 走 `senderType=agent` | — |
| **每框架独立** | 每个 Connector 内部状态隔离，互不干扰 | — |
| **渐进式替换** | 不一次性重写，逐个 Connector 验证后切流 | — |
| **🔒 最小权限** | 每个 Agent 的工具权限显式声明，默认全部关闭 | ✅ NEW |
| **🏖 沙箱隔离** | 文件/Shell 操作在沙箱内执行，与宿主机隔离 | ✅ NEW |
| **📡 事件驱动** | 长耗时 Agent 操作不阻塞 HTTP，走异步事件通知 | ✅ NEW |
| **🔄 双轨运行** | 迁移期间新旧架构共存，按 Agent 粒度切流 | ✅ NEW |

---

## 四、安全架构（新增章节 🆕）

### 4.1 威胁模型

```
攻击面                          风险等级      示例
─────────────────────────────────────────────────────────────
LLM 产生恶意 Shell 命令          CRITICAL     rm -rf /、curl 外泄数据
LLM 通过文件IO读取敏感文件        CRITICAL     读取 .env、数据库凭证
LLM 通过 Git 推送到外部仓库       HIGH         git push 到攻击者仓库
Agent 间通过消息管道传递恶意指令    MEDIUM      Agent A 诱骗 Agent B 执行危险操作
框架 API Key 泄露                 HIGH        connector_config 明文存储
Connector 返回的数据投毒           MEDIUM      框架返回伪造的操作记录
```

### 4.2 沙箱架构

```
Agent 工作目录隔离:
  /sandbox/{agent_id}/
    ├── workspace/         ← Agent 的文件操作范围（chroot/jail）
    ├── allowed_read/      ← 只读挂载的项目文件
    └── outputs/           ← Agent 产出物，经审查后移出

Shell 执行隔离:
  - 每个 Agent 在独立 Docker 容器中执行 Shell 命令
  - 容器网络: 仅允许访问内部服务（IM Core、Agent Runtime），禁止出站
  - 容器资源限制: CPU 2核, 内存 2GB, 磁盘 10GB
  - 命令白名单: 默认仅允许 git/go/npm/python/node/test 等开发工具
  - 禁止命令: rm -rf /, curl/wget (外网), sudo, chmod 777, > /dev/sda
```

### 4.3 权限模型

```python
# 每个 Agent 的工具权限显式配置，默认全部 DENY
class ToolPermission(Enum):
    FILE_READ = "file_read"           # 读取文件
    FILE_WRITE = "file_write"         # 写入文件（需审批）
    FILE_DELETE = "file_delete"       # 删除文件（需审批）
    SHELL_EXEC = "shell_exec"         # 执行命令（需审批）
    SHELL_INSTALL = "shell_install"   # 安装包（需审批）
    GIT_READ = "git_read"             # Git 读操作
    GIT_WRITE = "git_write"           # Git 写操作（需审批，严禁 force push）
    NET_OUTBOUND = "net_outbound"     # 外部网络访问（默认禁止）
    SEND_MESSAGE = "send_message"     # 发消息到频道
    CREATE_TASK = "create_task"       # 创建任务

# Agent 创建时的默认权限
DEFAULT_PERMISSIONS = {SEND_MESSAGE, CREATE_TASK}

# 需审批的操作（标记为 REQUIRES_APPROVAL）
APPROVAL_REQUIRED = {FILE_WRITE, FILE_DELETE, SHELL_EXEC, SHELL_INSTALL, GIT_WRITE}
```

### 4.4 审批流

```
Agent 执行需审批的操作:
  1. Agent 发出 tool_use 请求
  2. Connector 检查权限 → 如果 require_approval:
     a. 暂停 Agent 执行
     b. 在 IM 频道中发送审批卡片（含操作详情 + 风险等级）
     c. 等待人类点击 [批准] / [拒绝]
     d. 超时 5 分钟自动拒绝
  3. 批准后继续执行，全量记录到 audit_logs
```

### 4.5 审计链路

```
audit_logs 表扩展字段:
  - connector_type: 哪个框架执行的操作
  - tool_name: 调用了哪个工具
  - tool_params: 工具参数（脱敏后）
  - tool_result: 工具执行结果摘要
  - sandbox_id: 沙箱容器 ID
  - approval_id: 关联的审批记录
  - duration_ms: 操作耗时
  - exit_code: Shell 命令退出码
```

---

## 五、事件驱动架构（新增章节 🆕）

### 5.1 问题

当前架构是**同步请求-响应**：

```
HTTP POST /api/agents/{id}/think  →  等待 LLM 返回  →  返回文本
                                    (2-30秒)
```

引入外部框架后，一个任务可能**执行数分钟**：

```
Agent 收到"修复 #42 Bug"  →  读代码(5s) → 分析(10s) → 写修复(5s) → 跑测试(30s) → 调整(10s) → 完成
                                                                                       (~60秒+)
```

HTTP 请求不能阻塞这么久。

### 5.2 解决方案：Async Task + WebSocket 推送

```
┌─ Client ─────────────────────────────────────────────┐
│  WebSocket 长连接                                      │
│  订阅: channel:{id}, agent:{id}                        │
└────────────┬───────────────────────────────────────────┘
             │
┌────────────┼───────────────────────────────────────────┐
│  Agent Runtime                                          │
│                                                         │
│  POST /api/agents/{id}/act  →  返回 202 + task_id       │
│     │                                                   │
│     ├→ Connector.act() 异步执行                          │
│     │     │                                             │
│     │     ├→ EventBus.push(AGENT_THINKING, "...")       │
│     │     ├→ Connector 调用 LLM + 执行工具               │
│     │     ├→ EventBus.push(TOOL_EXECUTING, tool_name)   │
│     │     ├→ EventBus.push(TOOL_RESULT, result)         │
│     │     ├→ EventBus.push(AGENT_WRITING, "...")        │
│     │     └→ EventBus.push(AGENT_DONE, ActionResult)    │
│     │                                                   │
│     └→ WebSocket 推送实时状态到订阅的客户端               │
└─────────────────────────────────────────────────────────┘
```

### 5.3 事件类型定义

```protobuf
// 新增 shared/proto/maim/agent_event.proto
enum AgentEventType {
  AGENT_THINKING = 0;     // Agent 开始思考
  THOUGHT_CHUNK = 1;      // 流式思考片段
  TOOL_EXECUTING = 2;     // 正在执行工具 {tool_name, params}
  TOOL_RESULT = 3;        // 工具执行结果 {tool_name, success, summary}
  APPROVAL_NEEDED = 4;    // 需要人类审批 {action, risk_level}
  APPROVAL_GRANTED = 5;   // 审批通过
  APPROVAL_DENIED = 6;    // 审批拒绝
  AGENT_WRITING = 7;      // Agent 正在写回复
  AGENT_DONE = 8;         // 完成 {ActionResult}
  AGENT_ERROR = 9;        // 出错 {error_message}
}

message AgentEvent {
  string agent_id = 1;
  AgentEventType type = 2;
  string task_id = 3;
  google.protobuf.Struct payload = 4;
  int64 timestamp_ms = 5;
}
```

### 5.4 客户端体验

```
频道界面中 Agent 的状态实时更新:

  陈思远 [思考中...]            ← AGENT_THINKING
  陈思远 [🔧 正在读取 main.go]  ← TOOL_EXECUTING (read_file)
  陈思远 [🔧 正在运行 go test]  ← TOOL_EXECUTING (shell_exec)
  陈思远 [✍️ 正在输入...]       ← AGENT_WRITING
  陈思远: "修复了竞争条件..."    ← AGENT_DONE
```

---

## 六、重定义的 Connector 接口

### 6.1 第一代 vs 第二代接口

```python
# ── 第一代（当前）── "LLM 调用器" ──
class AgentConnector(ABC):
    async def think(self, context, memory) -> Thought:
        """调 LLM API，拿回文本"""
    async def think_stream(self, context, memory) -> AsyncIterator[str]:
        """流式拿文本"""

# ── 第二代（目标）── "框架集成器" ──
class AgentConnector(ABC):
    """针对一个完整的 Agent 框架的集成接口"""

    # ── 核心 ──
    @abstractmethod
    async def act(
        self,
        context: ConversationContext,
        soul_profile: SoulProfile,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]],
    ) -> ActionResult: ...

    @abstractmethod
    async def act_stream(
        self,
        context: ConversationContext,
        soul_profile: SoulProfile,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]],
    ) -> AsyncIterator[str]: ...

    # ── 能力声明 ──
    @abstractmethod
    def capability_inventory(self) -> CapabilityInventory: ...

    # ── 权限 ──
    @abstractmethod
    def required_tools(self) -> list[ToolDefinition]: ...
    @abstractmethod
    def approval_policy(self) -> dict[str, bool]: ...  # tool_name → requires_approval

    # ── 生命周期 ──
    @abstractmethod
    async def health_check(self) -> bool: ...
    @abstractmethod
    async def shutdown(self) -> None: ...


@dataclass
class ActionResult:
    """不再是只有一个 text 字段"""
    text: str = ""                              # 给人类看的文本回复
    tool_executions: list[ToolExecution] = []    # 执行过的工具及结果
    file_changes: list[FileChange] = []          # 文件变更清单
    artifacts: list[Artifact] = []               # 产出物
    reasoning_summary: str = ""                  # 推理过程摘要
    memory_candidates: list[dict] = []           # 值得存入记忆的内容


@dataclass
class CapabilityInventory:
    framework: str                    # "anthropic_agent" | "openclaw" | "hermes"
    text_generation: bool = True
    file_operations: bool = False     # 能否读写文件
    shell_execution: bool = False     # 能否执行命令
    git_operations: bool = False
    multi_step_planning: bool = False
    structured_output: bool = False
    multi_agent_orchestration: bool = False
    streaming: bool = False
    max_context_tokens: int = 8000
    supported_tools: list[str] = field(default_factory=list)
```

### 6.2 为什么用 `act()` 而不是 `think()`

| | `think()` | `act()` |
|:--|:---------|:--------|
| 含义 | "想一想然后告诉我" | "去做然后汇报结果" |
| 返回 | 一段文本 | 文本 + 操作记录 + 文件变更 + 产出物 |
| 耗时 | 秒级 | 秒级到分钟级 |
| 模式 | 同步阻塞 | 异步事件驱动 |

---

## 七、修正后的阶段分解

### Phase -1：前置研究与验证（2~3天） 🆕

**目标**：验证外部框架的实际可用性，避免基于错误假设做计划。

- [ ] **验证 OpenClaw 是否真实存在且有可用 API**
  - 搜索项目仓库、文档、API 规范
  - 确认是否有 Python SDK 或 REST API
  - 评估 API 稳定性与成熟度
  - 如果不存在或不成熟 → 降级为"未来预留"，不承诺 Phase 3 工期

- [ ] **验证 Hermes 是否真实存在且有可用 API**
  - 同上

- [ ] **验证 Anthropic API 工具调用能力边界**
  - tool_use 的实际可用工具数量上限
  - prompt caching 在长对话中的实际效果
  - 评估 streaming + tool_use 并用时的行为

- [ ] **输出研究报告**：每个框架的 API 能力清单、限制、集成风险

---

### Phase 0：定义目标架构与接口（3~4天）

**目标**：所有接口和协议在写代码之前冻结。

- [ ] 更新 `docs/ARCHITECTURE.md` 为第二代架构
- [ ] 冻结 `AgentConnector` v2 接口（含 `act()`, `act_stream()`, `CapabilityInventory`）
- [ ] 定义 `ActionResult`, `AgentEvent`, `ToolExecution`, `FileChange` 数据模型
- [ ] 定义 SoulProfile 序列化协议（SoulProfile → 各框架的 System Prompt 格式）
  - Anthropic: System message + cache_control
  - OpenClaw: Agent Profile JSON
  - Hermes: Agent Identity + Guardrails
- [ ] 定义 Memory 桥接协议（框架通过 REST API 访问 Runtime 的记忆）
- [ ] 定义沙箱接口：`SandboxManager` 的创建/销毁/隔离策略
- [ ] 拆除 `connector_type` 的概念混同（当前混同了 LLM provider 和框架类型）
  - `connector_type` 改为: `anthropic_agent | openclaw | hermes`
  - 框架内部的模型选择下沉到 `connector_config.model`
- [ ] 定义 EventBus 接口和 AgentEvent proto
- [ ] 定义 `approval_policy` 的交互协议

**关键输出（Phase 0 结束必须冻结）**:

```
├── shared/proto/maim/agent_event.proto   ← NEW
├── docs/ARCHITECTURE-v2.md               ← 更新
├── server/agent-runtime/src/connector/base_v2.py  ← NEW 接口
├── server/agent-runtime/src/sandbox.py            ← NEW 沙箱接口
└── server/agent-runtime/src/event_bus.py          ← NEW 事件总线接口
```

---

### Phase 1：瘦身 Agent Runtime（4~5天）

> 注意：Phase 1 在 Phase 0 接口冻结之后执行。此时还没有实现任何新的 Connector，只重构 Runtime 本身。

**目标**：将 ReasoningEngine 从"大脑"收缩为"调度器"，但**保持旧路径可用**（双轨）。

**策略：Feature Flag 双轨运行**

```python
# 在 agent_service.py 中
async def process_message(agent_id, channel_id, messages, participants):
    agent = await self.db.get_agent(agent_id)

    # Feature flag: 按 Agent 粒度切流
    if agent.get("connector_type") in ("anthropic_agent", "openclaw", "hermes"):
        # 新路径: ConnectorRouter → 外部框架
        return await self.connector_router.act(agent, ...)
    else:
        # 旧路径: ReasoningEngine (保持兼容)
        return await self.reasoning_engine.process_message(agent_id, ...)
```

**改动清单**：

| 组件 | 变更 | 是否破坏旧路径 |
|:-----|:-----|:---:|
| `ReasoningEngine` | 标记为 `@deprecated`，保留不动 | ❌ 不破坏 |
| 新增 `ConnectorRouter` | 按 `connector_type` 分发到 Connector | ❌ 新组件 |
| 新增 `SoulSerializer` | SoulProfile → Dict/JSON (各 Connector 自行转换) | ❌ 新组件 |
| 新增 `MemoryService` | 抽出记忆 CRUD + 语义搜索为独立服务 | ❌ 不破坏 |
| 新增 `EventBus` | Redis pub/sub 实现 AgentEvent 推送 | ❌ 新组件 |
| 新增 `SandboxManager` | Docker SDK 管理沙箱容器 | ❌ 新组件 |
| `agent_service.py` | 添加 `connector_type` 字段的路由逻辑 | ❌ 向后兼容 |
| `db.py` | 新增 `tool_permissions` 表、扩展 `audit_logs` 表 | ❌ 新增表 |
| 状态管理 | 保持现有状态机，新增 `AWAITING_APPROVAL` 状态 | ❌ 新增状态值 |

**验收标准**：
- ✅ 旧路径 Agent（`connector_type` 为空或 `openai_compatible`/`claude_code`）功能完全不变
- ✅ 新路径 Agent（`connector_type = "anthropic_agent"`）走 ConnectorRouter
- ✅ EventBus 能通过 WebSocket 推送事件到客户端
- ✅ SandboxManager 能创建/销毁 Docker 容器
- ✅ 单元测试覆盖率 ≥ 80%
- ✅ 集成测试通过：新旧 Agent 共存于同一频道

---

### Phase 2：Anthropic Agent Connector（7~10天）

> 原名"Claude Code Connector"。改名原因：我们用的是 Anthropic API + 自主工具循环，不是 Claude Code CLI 产品。这消除了歧义。

**价值**：第一个真正能干活的 AI 员工。能力包括：读写文件、执行 Shell 命令、Git 操作、代码搜索。

**架构**：

```
┌─ AnthropicAgentConnector ──────────────────────────────────┐
│                                                             │
│  act(soul_profile, memory_context, event_callback)          │
│     │                                                       │
│     ├─ 1. 序列化 SoulProfile → Anthropic System Prompt     │
│     │     (含 identity/persona/values/red_lines)            │
│     │     + cache_control breakpoint                        │
│     │                                                       │
│     ├─ 2. 注入 MemoryContext                                │
│     │     (从 Runtime 的 MemoryService 检索的相关记忆)      │
│     │                                                       │
│     ├─ 3. 构建消息历史（从 ConversationContext）            │
│     │                                                       │
│     ├─ 4. Agent Loop (最多 MAX_ROUNDS=20):                 │
│     │     │                                                 │
│     │     ├─ anthropic.messages.create()                    │
│     │     ├─ 如果是 text → 累积文本，emit THOUGHT_CHUNK    │
│     │     ├─ 如果是 tool_use:                              │
│     │     │   ├─ 检查权限 (PermissionModel)                │
│     │     │   ├─ 如需审批 → emit APPROVAL_NEEDED           │
│     │     │   │            等待审批或超时                   │
│     │     │   ├─ emit TOOL_EXECUTING                       │
│     │     │   ├─ 在 Sandbox 内执行工具                     │
│     │     │   ├─ emit TOOL_RESULT                          │
│     │     │   ├─ 记录到 audit_logs                         │
│     │     │   └─ 将结果追加到 messages                     │
│     │     └─ 如无 tool_use → 循环结束                      │
│     │                                                       │
│     └─ 5. 构建 ActionResult                                │
│           text + tool_executions + file_changes + artifacts │
│                                                             │
│  工具集（12个）:                                            │
│    📁 read_file(path)          — 读文件                     │
│    📁 write_file(path, content) — 写文件（需审批）          │
│    📁 list_files(dir)          — 列出目录                   │
│    📁 search_code(pattern)     — 代码搜索 (ripgrep)         │
│    💻 shell_exec(cmd, cwd)    — 执行命令（需审批，沙箱内）  │
│    🔀 git_status()             — Git 状态                   │
│    🔀 git_diff()               — Git diff                   │
│    🔀 git_branch(name)         — 创建分支                   │
│    🔀 git_commit(msg)          — 提交（需审批）             │
│    💬 send_message(content)    — 发消息到频道               │
│    📋 create_task(title,desc)  — 创建任务                   │
│    📋 update_task(id, status)  — 更新任务状态               │
└─────────────────────────────────────────────────────────────┘
```

**关键设计决策**：

| 决策 | 选择 | 原因 |
|:-----|:-----|:-----|
| API 方式 | Anthropic SDK 直连 | Claude Code CLI 不是 headless 服务，子进程模式不可靠 |
| 工具循环 | 自己实现（Python） | Anthropic 不提供 Agent 框架，我们自己在 Connector 内实现 |
| 流式输出 | SDK streaming + 工具循环交替 | 思考内容实时推，工具执行间插状态推送 |
| Prompt Caching | Soul Profile 部分标记 cache_control | 节省 90% 的 System Prompt token 成本 |
| 最大轮次 | 20 轮（可配置） | 防止无限循环，超过后返回已累积的结果 |

**验收标准**：
- ✅ Agent 收到"修复 backend/main.go 第42行Bug" → 读文件 → 改代码 → 跑测试 → 汇报结果
- ✅ Agent 收到"创建一个 Python 脚本分析 CSV" → 写文件 → 执行 → 验证输出
- ✅ 所有文件操作在沙箱内，不污染宿主机
- ✅ 写文件/Shell/Git 操作触发审批卡片
- ✅ 操作全量记入 audit_logs
- ✅ Agent 回复中附带操作摘要（改了什么文件、跑了什么命令、结果如何）
- ✅ 客户端实时看到 Agent 的状态变化

---

### Phase 3：WorkflowEngine — 自建轻量 DAG 编排（4~5天）🔄

> 🔴 原计划为 OpenClaw Connector。Phase -1 研究发现：**OpenClaw 是一个竞品 AI 网关平台（Node.js），不是一个可嵌入的 Python 框架。** 将其作为"大脑框架"嵌入 Multi-agent-IM 在架构上不合理。
> 详见 [PHASE-1-RESEARCH.md](PHASE-1-RESEARCH.md)

**价值**：多 Agent DAG 工作流编排 + 子 Agent 委派。不依赖外部框架。

**设计**：

```python
class WorkflowEngine:
    """
    轻量 DAG 工作流引擎。

    核心功能：
    - 任务 DAG 定义（节点 = Agent, 边 = 依赖关系）
    - 子 Agent 委派（parent task → child subtasks）
    - 条件分支（根据上游结果决定下游）
    - 并行分发（无依赖关系的任务并行执行）
    - 状态追踪（每个节点的状态通过 EventBus 实时推送）
    """

    async def create_workflow(self, dag: TaskDAG) -> str: ...
    async def execute_node(self, node_id: str, agent_id: str) -> ActionResult: ...
    async def get_status(self, workflow_id: str) -> WorkflowStatus: ...
```

**验收标准**：
- ✅ 一个 Agent 可创建 DAG 工作流并委派子任务给其他 Agent
- ✅ 无依赖关系的子任务并行执行
- ✅ 上游任务输出作为下游任务输入
- ✅ IM 中可看到工作流整体执行状态

---

### Phase 4：Hermes Agent Connector（5~7天）🔄

> 前置条件：Phase -1 研究确认 Hermes Agent (NousResearch) **可用作嵌入式 Python 库** ✅
> `from run_agent import AIAgent` 直接可用。详见 [PHASE-1-RESEARCH.md](PHASE-1-RESEARCH.md)
>
> ⚠️ 工期从 3-5 天调整为 5-7 天（需处理同步→异步桥接 + CLI 输出抑制 + 工具集白名单控制）

**价值**：全功能 Agent 框架——70+ 工具、多步规划、子 Agent 委派、上下文压缩。

**集成方式**：

```python
# 在 HermesConnector 中包装 AIAgent
from run_agent import AIAgent

class HermesConnector(AgentConnector):
    async def act(self, context, soul_profile, memory_context, event_callback):
        agent = AIAgent(
            model=soul_profile.identity.llm_model,
            quiet_mode=True,             # 抑制 CLI 输出
            skip_memory=True,            # 使用我们的 MemoryService
            skip_context_files=True,     # 不加载 AGENTS.md
            enabled_toolsets=[...],      # 根据 agent 权限白名单
        )
        # AIAgent 是同步 API，用 asyncio.to_thread() 包装
        result = await asyncio.to_thread(
            agent.run_conversation,
            user_message=context.messages[-1]["content"],
            conversation_history=self._adapt_history(context.messages[:-1]),
        )
        return self._adapt_result(result)
```

**验收标准**：
- ✅ Agent 可做 plan → execute → verify → iterate 多步规划
- ✅ 可使用 Hermes 的 70+ 工具（按权限白名单控制）
- ✅ 同步→异步桥接流畅，不阻塞 event loop
- ✅ IM 中实时展示 Agent 的工具调用过程

---

### Phase 5：UI 改造 + 联调（4~6天）

- [ ] Agent 创建页：从"选择 LLM"改为"选择大脑框架" + 框架能力说明卡片
- [ ] Agent 详情页：展示 CapabilityInventory 雷达图
- [ ] Agent 详情页：展示框架级配置（工作目录、工具权限开关、审批策略）
- [ ] 频道界面：实时 Agent 状态流（TOOL_EXECUTING / APPROVAL_NEEDED 等）
- [ ] 审批卡片 UI：操作详情 + 风险等级 + 批准/拒绝按钮
- [ ] 操作记录面板：Agent 执行过的工具调用历史
- [ ] 框架对比页：更新为框架级对比（不再是比较 LLM 价格）
- [ ] 全局联调：双轨 Agent 共存测试
- [ ] E2E 测试：从创建 Agent 到完成任务的完整链路

---

## 八、修正后的时间线

```
Phase -1  前置研究 ✅       ██░░░░░░  已完成 (2026-06-09)
Phase 0   定义接口          ███░░░░░  3~4天
Phase 1   瘦身 Runtime      ████░░░░  4~5天  ← 双轨，不破坏旧 Agent
Phase 2   Anthropic Agent   ███████░  7~10天  ← 最复杂，最长工期
Phase 3   WorkflowEngine    ███░░░░░  4~5天   ← 自建 DAG 编排 (替代 OpenClaw)
Phase 4   Hermes Agent      ████░░░░  5~7天   ← 同步→异步桥接 (工期 +2天)
Phase 5   UI + 联调         ████░░░░  4~6天
                             ────────
                             27~37天（6~8周）
```

**依赖关系**：
```
Phase -1 ──✅ 完成
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 5
                 └────→ Phase 3 ──→ Phase 5
                 └────→ Phase 4 ──→ Phase 5
```

Phase 2/3/4 可在 Phase 1 完成后**并行**推进（如果有多人），或串行推进（单人）。

---

## 九、双轨运行与回滚策略（新增章节 🆕）

### 9.1 双轨运行

```
迁移路径（按 Agent 粒度）:

  全部 Agent (旧架构)
    │
    ├─→ Phase 1: Runtime 支持双轨
    │     Agent A (旧) ──→ ReasoningEngine (旧路径)
    │     Agent B (新) ──→ ConnectorRouter (新路径)
    │     两者共存于同一频道
    │
    ├─→ Phase 2: 创建第一个 Anthropic Agent
    │     验证正常工作
    │
    ├─→ 逐步迁移: 将旧 Agent 的 connector_type 改为 "anthropic_agent"
    │     每次迁移一个，观察 24 小时
    │
    └─→ 最终: 所有 Agent 走新路径
          ReasoningEngine 标记 deprecated，但保留代码
```

### 9.2 每阶段回滚方案

| 阶段 | 回滚方式 |
|:-----|:--------|
| Phase 1 | 将 Agent 的 `connector_type` 改回旧值 → 恢复走 ReasoningEngine |
| Phase 2 | 同上 + 删除新创建的 Anthropic Agent（数据保留） |
| Phase 3-4 | 同上 |
| Phase 5 | Git revert + 重新部署旧版前端 |

**不可逆的操作**：Agent 在沙箱内产生的文件变更。这些保留在沙箱目录中，回滚不删除。

---

## 十、测试策略（新增章节 🆕）

| 阶段 | 测试层次 | 具体内容 |
|:-----|:--------|:--------|
| Phase 0 | 接口测试 | Connector v2 接口的抽象方法完整性检查 |
| Phase 1 | 单元测试 | SoulSerializer 各框架格式输出正确性 |
| Phase 1 | 单元测试 | MemoryService 独立 CRUD + 语义搜索 |
| Phase 1 | 单元测试 | EventBus pub/sub 正确性 |
| Phase 1 | 单元测试 | SandboxManager 容器生命周期 |
| Phase 1 | 集成测试 | 新旧 Agent 共存于同一频道 |
| Phase 2 | 单元测试 | 每个工具的独立测试（模拟 Anthropic API 响应） |
| Phase 2 | 集成测试 | Mock Anthropic API → 完整 Agent Loop |
| Phase 2 | E2E 测试 | 真实 Anthropic API: "帮我修 Bug" → 完整链路 |
| Phase 2 | 安全测试 | 恶意命令拦截、文件访问越界、审批绕过测试 |
| Phase 2 | 性能测试 | Agent 并发数、Sandbox 资源消耗 |
| Phase 3-4 | 集成测试 | Mock 框架 API → 完整 Agent Loop |
| Phase 5 | E2E 测试 | 从前端创建 Agent → 频道协作 → 任务闭环 |
| Phase 5 | 回归测试 | 所有 Phase 0-6 功能不受影响 |

---

## 十一、成功指标（新增章节 🆕）

### Phase 1 完成标准
- [ ] 旧路径 Agent 在 Phase 1 前后行为一致（回归测试全绿）
- [ ] 新路径 Agent 能成功调用 `ConnectorRouter.act()`
- [ ] EventBus 推送延迟 < 100ms
- [ ] Sandbox 创建时间 < 3s

### Phase 2 完成标准
- [ ] Agent 收到编程任务 → 能在沙箱内完成读/写/执行 → 返回正确结果
- [ ] 工具执行成功率 ≥ 80%
- [ ] Agent Loop 平均轮次 ≤ 8
- [ ] 审批流延迟 < 30s（从 APPROVAL_NEEDED 到人类决策）
- [ ] 零安全逃逸（沙箱测试套件全绿）

### Phase 5 完成标准
- [ ] 人类视角：Agent 从"只会聊天"变成"能干活的同事"
- [ ] 一个频道内可同时有 Anthropic/OpenClaw/Hermes Agent 正常协作
- [ ] 审批流程流畅可用
- [ ] E2E 测试全覆盖

---

## 十二、可观测性设计（新增章节 🆕）

```
监控指标（Prometheus + Grafana）:

  agent_act_duration_seconds     # Agent act() 总耗时 (histogram)
  agent_tool_execution_total     # 工具调用计数（按 tool_name 分）
  agent_tool_errors_total        # 工具调用错误计数
  agent_approval_pending_count   # 等待审批的操作数
  agent_sandbox_active           # 活跃沙箱数
  connector_api_errors_total     # 外部 API 错误计数
  connector_api_latency_seconds  # 外部 API 延迟

告警规则:
  - agent_act_duration > 300s → Warning
  - agent_tool_errors_total 5m 增长 > 10 → Critical
  - agent_approval_pending > 20 → Warning（审批积压）
  - connector_api_errors 5m 增长 > 5 → Critical
```

---

## 十三、风险矩阵（更新 🆕）

| 风险 | 概率 | 影响 | v1 应对 | v2 升级应对 |
|:-----|:----:|:----:|:--------|:----------|
| 外部 Agent 执行危险操作 | 高 | **严重** | 无 | 沙箱隔离 + 权限模型 + 审批流 |
| Claude Code 不是 SDK 产品 | 高 | 中 | CLI 子进程 | **确认事实**：用 Anthropic API 自建工具循环 |
| OpenClaw/Hermes 不存在或不成熟 | 中 | 中 | 等 Phase 3 再看 | **Phase -1** 提前验证，不可用则降级 |
| 同步架构无法应对长耗时 | 高 | 高 | 无 | **事件驱动架构** + Async Task |
| 旧 Agent 功能回归 | 中 | 高 | 跑测试 | **双轨运行** + 按 Agent 粒度切流 + 回滚方案 |
| Soul 注入效果不可控 | 中 | 中 | A/B 测试 | 增加 Soul 注入效果的评测指标 |
| API 成本失控 | 中 | 中 | 无 | 增加 token 消耗追踪 + 单 Agent 日预算上限 |
| 工期估计不准确 | 中 | 中 | 4-6 周 | **6-8 周** + Phase -1 缓冲 |

---

## 十四、附录

### A. 为什么必须改名为 "Anthropic Agent Connector"

"Claude Code" 是 Anthropic 的 CLI 工具产品。它没有一个可供程序调用的 headless API。我们无法"集成 Claude Code"——我们只能：
1. 用 Anthropic SDK 直接调 Claude API（自建工具循环）← 我们的方案
2. 把 Claude Code CLI 当子进程 spawn（不可靠、无结构化输出）

当前代码里的 `ClaudeCodeConnector` 已经是方案 1——它只是名字里有 "Claude Code" 但实际用的是 `anthropic.AsyncAnthropic`。改名消除歧义。

### B. Anthropic Agent Connector 与旧 Connector 的关系

旧的 `ClaudeCodeConnector` 和 `OpenAICompatibleConnector` 在 Phase 1 保留不动，供旧路径 Agent 使用。Phase 2 的 `AnthropicAgentConnector` 是**全新的实现**，不基于旧代码重构。旧 Connector 在全部 Agent 迁移完毕后标记 deprecated 但不删除（保留作为简单 LLM 调用的回退选项）。

### C. 数据库变更汇总

```sql
-- Phase 1 新增
ALTER TABLE agents ADD COLUMN connector_type_v2 VARCHAR(50);  -- 新框架标识符
ALTER TABLE agents ADD COLUMN tool_permissions JSONB DEFAULT '{}';
ALTER TABLE agents ADD COLUMN sandbox_config JSONB DEFAULT '{}';

CREATE TABLE tool_executions (
  id UUID PRIMARY KEY,
  agent_id UUID REFERENCES agents(id),
  task_id UUID,
  tool_name VARCHAR(100),
  tool_params JSONB,
  tool_result JSONB,
  sandbox_id VARCHAR(100),
  approval_id UUID,
  duration_ms INT,
  exit_code INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE approvals (
  id UUID PRIMARY KEY,
  agent_id UUID REFERENCES agents(id),
  channel_id UUID,
  action_type VARCHAR(100),
  action_detail JSONB,
  risk_level VARCHAR(20),
  status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING | APPROVED | DENIED | TIMEOUT
  approved_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

-- 扩展 audit_logs
ALTER TABLE audit_logs ADD COLUMN connector_type VARCHAR(50);
ALTER TABLE audit_logs ADD COLUMN tool_execution_id UUID;
ALTER TABLE audit_logs ADD COLUMN sandbox_id VARCHAR(100);
```

### D. 新依赖项

```
Python:
  - docker (Docker SDK for Python — 管理沙箱容器)
  - anthropic (已有，升级到最新版)

Go:
  - 无需新依赖（事件推送通过现有 WebSocket Hub）

Infra:
  - Docker daemon（需可用，用于沙箱容器）
```
