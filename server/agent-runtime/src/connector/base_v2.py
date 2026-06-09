"""
AgentConnector v2 — 第二代接口：框架集成器。

v1 → v2 核心变化：
  think()  → act()           文本生成 → 行动执行
  Thought  → ActionResult    只有文本 → 文本 + 操作记录 + 文件变更 + 产出物
  无概念   → CapabilityInventory  框架自描述能力
  无概念   → approval_policy      操作需审批声明

设计原则：
  - 灵魂与大脑分离：SoulProfile 由 Runtime 管理，注入各框架
  - 每框架独立：每个 Connector 保持内部状态隔离
  - 权限显式声明：每个工具标记是否需要审批
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable

# ── Re-export v1 types that remain valid ──────────────────────────
from connector.base import (
    AgentConnector as AgentConnectorV1,  # deprecated, kept for backward compat
    ConversationContext,
    MemorySnapshot,
    Thought,
    ToolResult,
    CONNECTOR_REGISTRY,  # v1 registry — v2 adds CONNECTOR_REGISTRY_V2
)

# ───────────────────────────────────────────────────────────────────
# 核心枚举
# ───────────────────────────────────────────────────────────────────


class AgentEventType(str, Enum):
    """推到客户端的 Agent 实时事件类型。"""
    # 生命周期
    AGENT_STARTED = "agent_started"        # Agent 开始执行
    AGENT_DONE = "agent_done"              # Agent 执行完成
    AGENT_ERROR = "agent_error"            # Agent 执行出错

    # 推理过程
    THINKING = "thinking"                  # Agent 正在思考
    THOUGHT_CHUNK = "thought_chunk"        # 流式思考文本片段
    REASONING_TRACE = "reasoning_trace"    # 推理过程文本

    # 工具执行
    TOOL_EXECUTING = "tool_executing"      # 正在执行工具 {tool_name, params}
    TOOL_RESULT = "tool_result"            # 工具执行结果 {tool_name, success, summary}
    TOOL_ERROR = "tool_error"              # 工具执行错误

    # 人类审批
    APPROVAL_NEEDED = "approval_needed"    # 需人类审批 {action, risk_level, detail}
    APPROVAL_GRANTED = "approval_granted"  # 审批通过
    APPROVAL_DENIED = "approval_denied"    # 审批被拒
    APPROVAL_TIMEOUT = "approval_timeout"  # 审批超时

    # 进度
    PROGRESS = "progress"                  # 进度更新 {current_step, total_steps, message}


class ToolPermission(str, Enum):
    """工具权限枚举。Agent 创建时默认全部 DENY，按需开启。"""
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    SHELL_EXEC = "shell_exec"
    SHELL_INSTALL = "shell_install"
    GIT_READ = "git_read"
    GIT_WRITE = "git_write"
    NET_OUTBOUND = "net_outbound"
    SEND_MESSAGE = "send_message"
    CREATE_TASK = "create_task"
    DELEGATE_TASK = "delegate_task"


class RiskLevel(str, Enum):
    """工具操作的风险等级，决定审批策略。"""
    SAFE = "safe"        # 纯读取操作，不需要审批
    LOW = "low"          # 低风险操作
    MEDIUM = "medium"    # 中风险操作，需要审批
    HIGH = "high"        # 高风险操作，强制审批 + 审计
    CRITICAL = "critical"  # 最高风险，需要双重审批


# ───────────────────────────────────────────────────────────────────
# 数据模型
# ───────────────────────────────────────────────────────────────────


@dataclass
class ToolDefinition:
    """工具定义 — 声明一个框架 Connector 支持的工具。"""
    name: str                                          # 工具名称（如 "read_file"）
    description: str                                   # 工具描述
    parameters: dict[str, Any]                         # JSON Schema 参数定义
    permission: ToolPermission                         # 所属权限
    risk_level: RiskLevel = RiskLevel.SAFE             # 风险等级
    requires_approval: bool = False                    # 是否需要人类审批
    approval_timeout_s: int = 300                      # 审批超时时间（秒）
    max_result_size_chars: int = 100_000               # 结果最大字符数


@dataclass
class ToolExecution:
    """单次工具执行的记录。"""
    tool_name: str
    tool_params: dict[str, Any]
    success: bool
    result_summary: str = ""
    result_detail: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    duration_ms: float = 0
    sandbox_id: str = ""
    approval_id: str = ""
    risk_level: RiskLevel = RiskLevel.SAFE


@dataclass
class FileChange:
    """文件变更记录。"""
    path: str
    operation: str     # "create" | "modify" | "delete"
    diff: str = ""     # unified diff（可选）
    size_before: int = 0
    size_after: int = 0


@dataclass
class Artifact:
    """Agent 产出物。"""
    name: str
    artifact_type: str   # "file" | "code" | "report" | "link" | "other"
    uri: str = ""        # 存储位置（MinIO URL / 本地路径）
    mime_type: str = ""
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Agent 行动结果 — v2 核心返回类型。

    v1 Thought:  { text, actions, reasoning_trace }
    v2 ActionResult: { text, tool_executions, file_changes, artifacts, memory_candidates }
    """
    # 文本回复
    text: str = ""

    # 操作记录
    tool_executions: list[ToolExecution] = field(default_factory=list)

    # 变更追踪
    file_changes: list[FileChange] = field(default_factory=list)

    # 产出物
    artifacts: list[Artifact] = field(default_factory=list)

    # 推理过程
    reasoning_trace: str = ""

    # 记忆候选（值得存入长期记忆的内容）
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)

    # 元数据
    total_duration_ms: float = 0
    tokens_used: int = 0
    rounds: int = 0  # agent loop 轮次
    success: bool = True
    error_message: str = ""


@dataclass
class CapabilityInventory:
    """框架能力清单 — 每个 Connector 自描述能做什么、不能做什么。"""
    # 框架标识
    framework: str = ""  # "anthropic_agent" | "hermes_agent" | "workflow_engine"

    # 基础能力
    text_generation: bool = True
    streaming: bool = False
    structured_output: bool = False  # JSON Schema 约束

    # 文件系统
    file_read: bool = False
    file_write: bool = False
    file_delete: bool = False
    file_search: bool = False

    # 执行环境
    shell_execution: bool = False
    code_execution: bool = False
    browser_automation: bool = False

    # 版本控制
    git_read: bool = False
    git_write: bool = False

    # 网络
    web_search: bool = False
    web_fetch: bool = False
    api_call: bool = False

    # Agent 协作
    multi_agent_orchestration: bool = False
    sub_agent_delegation: bool = False
    human_approval: bool = False

    # 上下文
    max_context_tokens: int = 8000
    max_output_tokens: int = 4096
    supports_prompt_caching: bool = False

    # 工具
    supported_tools: list[str] = field(default_factory=list)
    max_tools_per_request: int = 20

    # 扩展
    extra: dict[str, Any] = field(default_factory=dict)

    def to_frontend(self) -> dict[str, Any]:
        """序列化为前端可展示的格式。"""
        return {
            "framework": self.framework,
            "capabilities": {
                "text_generation": self.text_generation,
                "streaming": self.streaming,
                "structured_output": self.structured_output,
            },
            "filesystem": {
                "read": self.file_read,
                "write": self.file_write,
                "delete": self.file_delete,
                "search": self.file_search,
            },
            "execution": {
                "shell": self.shell_execution,
                "code": self.code_execution,
                "browser": self.browser_automation,
            },
            "version_control": {
                "read": self.git_read,
                "write": self.git_write,
            },
            "network": {
                "web_search": self.web_search,
                "web_fetch": self.web_fetch,
                "api_call": self.api_call,
            },
            "collaboration": {
                "multi_agent": self.multi_agent_orchestration,
                "sub_agent": self.sub_agent_delegation,
                "human_approval": self.human_approval,
            },
            "context": {
                "max_tokens": self.max_context_tokens,
                "max_output": self.max_output_tokens,
                "prompt_caching": self.supports_prompt_caching,
            },
            "tools": self.supported_tools,
            "extra": self.extra,
        }


# ───────────────────────────────────────────────────────────────────
# 第二代 Connector 接口
# ───────────────────────────────────────────────────────────────────


class AgentConnectorV2(ABC):
    """第二代 Agent 框架集成接口。

    与 v1 (AgentConnector) 的本质区别：
      v1.think()  →  "帮我想一想，给我文字"
      v2.act()    →  "去做这件事，向我汇报你做了什么"

    每个实现对应一个完整的外部 Agent 框架（Anthropic Agent / Hermes Agent 等）。
    Agent Runtime 通过此接口将任务委托给外部框架，自己只做调度和记忆管理。
    """

    # ── 标识 ──────────────────────────────────────────────────────

    @abstractmethod
    def connector_name(self) -> str:
        """连接器唯一标识，如 "anthropic_agent"。"""
        ...

    @abstractmethod
    def connector_version(self) -> str:
        """连接器版本。"""
        ...

    # ── 生命周期 ──────────────────────────────────────────────────

    @abstractmethod
    async def initialize(self, agent_config: dict[str, Any]) -> None:
        """初始化连接器。

        agent_config 包含:
          - agent_id: 在 Multi-agent-IM 中的唯一 ID
          - connector_name: 框架标识符
          - model: 框架内使用的模型
          - api_key: API 密钥
          - base_url: 自定义 endpoint（可选）
          - tool_permissions: 已开启的工具权限列表
          - sandbox_config: 沙箱配置
          - extra: 框架特定配置
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查。返回 False 表示连接器不可用。"""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """优雅关闭，释放资源（沙箱、API 连接等）。"""
        ...

    # ── 核心：行动执行 ────────────────────────────────────────────

    @abstractmethod
    async def act(
        self,
        context: ConversationContext,
        soul_profile: "SoulProfile",                          # type: ignore
        memory_context: MemorySnapshot,
        event_callback: Callable[["AgentEvent"], Awaitable[None]] | None = None,
    ) -> ActionResult:
        """执行行动。

        Args:
            context: 当前对话上下文（频道、消息历史、参与者）
            soul_profile: 灵魂画像（由 Runtime 的 SoulSerializer 构建，注入到框架）
            memory_context: 相关记忆快照（由 Runtime 的 MemoryService 检索）
            event_callback: 事件回调（用于实时推送状态到客户端）

        Returns:
            ActionResult: 文本 + 操作记录 + 文件变更 + 产出物 + 记忆候选

        框架内部负责：
          - 将 SoulProfile 转换为框架自身的 prompt 格式
          - 工具调用循环
          - 错误重试
          - 通过 event_callback 推送实时事件
        """
        ...

    @abstractmethod
    async def act_stream(
        self,
        context: ConversationContext,
        soul_profile: "SoulProfile",
        memory_context: MemorySnapshot,
        event_callback: Callable[["AgentEvent"], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        """流式执行行动 — 逐步产出文本（用于实时显示"Agent 正在输入"）。

        与 act() 的关系：实现至少其中之一。act() 用于非流式场景，act_stream() 用于流式。
        默认实现调用 act() 并 yield 整个 text，子类覆盖以获得真正的流式行为。
        """
        result = await self.act(context, soul_profile, memory_context, event_callback)
        yield result.text

    # ── 能力声明 ──────────────────────────────────────────────────

    @abstractmethod
    def capability_inventory(self) -> CapabilityInventory:
        """返回框架的完整能力清单。

        Agent Runtime 据此判断：
          - 这个框架能不能执行文件操作？
          - 能不能执行 Shell 命令？
          - 支持多少上下文 token？
          - 支持哪些工具？

        前端据此展示框架的能力对比卡片。
        """
        ...

    # ── 工具定义 ──────────────────────────────────────────────────

    @abstractmethod
    def tool_definitions(self) -> list[ToolDefinition]:
        """返回框架所有可用工具的完整定义（schema + 权限 + 风险等级）。

        Agent Runtime 据此：
          - 与 Agent 的 tool_permissions 比对，生成白名单
          - 为需要审批的工具注入审批拦截逻辑
        """
        ...

    def tools_for_permissions(self, permissions: list[str]) -> list[ToolDefinition]:
        """根据 Agent 的权限白名单过滤工具集。"""
        allowed = set(permissions)
        return [t for t in self.tool_definitions() if t.permission.value in allowed]

    # ── 审批策略 ──────────────────────────────────────────────────

    def approval_policy(self) -> dict[str, bool]:
        """返回每个工具是否需要审批的默认策略。

        Returns:
            {tool_name: requires_approval}
        """
        return {
            t.name: t.requires_approval
            for t in self.tool_definitions()
        }


# ───────────────────────────────────────────────────────────────────
# AgentEvent — 实时推送事件
# ───────────────────────────────────────────────────────────────────


@dataclass
class AgentEvent:
    """Agent 执行过程中推送到客户端的实时事件。"""
    agent_id: str
    event_type: AgentEventType
    agent_name: str = ""       # ← v2: display name for UI
    task_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp_ms: int = 0  # epoch millis

    def to_ws_message(self) -> dict[str, Any]:
        """转换为 WebSocket 推送的消息格式。"""
        import time
        return {
            "type": "agent_event",
            "agent_id": self.agent_id,
            "event": self.event_type.value,
            "task_id": self.task_id,
            "payload": self.payload,
            "ts": self.timestamp_ms or int(time.time() * 1000),
        }

    def to_dict(self) -> dict[str, Any]:
        """兼容 event_bus.EventBus 的序列化接口。"""
        import time
        return {
            "type": "agent_event",
            "agent_id": str(self.agent_id),
            "agent_name": str(self.agent_name or ""),
            "event": self.event_type.value,
            "task_id": str(self.task_id) if self.task_id else "",
            "payload": {str(k): v for k, v in self.payload.items()},
            "ts": self.timestamp_ms or int(time.time() * 1000),
        }

    def to_json(self) -> str:
        """兼容 event_bus.EventBus 的 JSON 序列化。"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ───────────────────────────────────────────────────────────────────
# v2 Connector Registry
# ───────────────────────────────────────────────────────────────────

CONNECTOR_REGISTRY_V2: dict[str, type[AgentConnectorV2]] = {}


def register_connector_v2(name: str):
    """装饰器：注册 v2 Connector 实现。"""
    def wrapper(cls: type[AgentConnectorV2]):
        CONNECTOR_REGISTRY_V2[name] = cls
        return cls
    return wrapper


def get_connector_v2(name: str) -> type[AgentConnectorV2]:
    """查找 v2 Connector。"""
    if name not in CONNECTOR_REGISTRY_V2:
        available = list(CONNECTOR_REGISTRY_V2.keys())
        raise ValueError(
            f"Unknown v2 connector: '{name}'. "
            f"Available: {available}"
        )
    return CONNECTOR_REGISTRY_V2[name]
