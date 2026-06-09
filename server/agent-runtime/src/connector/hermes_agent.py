"""
HermesAgentConnector — v2 Connector wrapping Hermes Agent (NousResearch).

Hermes Agent 是一个独立的 Python Agent 框架，提供 70+ 工具 / 28+ 工具集。
本 Connector 将其包装为 AgentConnectorV2，使 Multi-agent-IM 的 Agent 可以
将 Hermes 作为"大脑"后端。

集成要点:
  1. AIAgent 是同步 API → asyncio.to_thread() 桥接
  2. AIAgent 非线程安全 → 每个请求创建新实例
  3. quiet_mode=True → 抑制 CLI 输出
  4. skip_memory=True + skip_context_files=True → 使用我们的服务
  5. enabled_toolsets 按 agent.tool_permissions 白名单过滤
  6. 如果 Hermes 未安装 → 优雅降级（返回错误信息）

安装:
  pip install git+https://github.com/NousResearch/hermes-agent.git
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Awaitable, Callable

from connector.base import ConversationContext, MemorySnapshot
from connector.base_v2 import (
    AgentConnectorV2,
    ActionResult,
    AgentEvent,
    AgentEventType,
    CapabilityInventory,
    ToolDefinition,
    ToolPermission,
    RiskLevel,
    register_connector_v2,
)

logger = logging.getLogger(__name__)

# ── Hermes 可用性检测 ───────────────────────────────────────────

HERMES_AVAILABLE = False
AIAgent = None
_deferred_error = ""

try:
    from run_agent import AIAgent as _AIAgent  # noqa: F401
    AIAgent = _AIAgent
    HERMES_AVAILABLE = True
except ImportError as e:
    _deferred_error = (
        f"Hermes Agent not installed. "
        f"Install with: pip install git+https://github.com/NousResearch/hermes-agent.git "
        f"(ImportError: {e})"
    )

# ── Toolset 映射 ────────────────────────────────────────────────

# Multi-agent-IM ToolPermission → Hermes toolsets
PERMISSION_TO_HERMES_TOOLSET: dict[str, list[str]] = {
    "file_read":       ["file"],
    "file_write":      ["file"],
    "file_delete":     [],
    "shell_exec":      ["terminal"],
    "shell_install":   ["terminal"],
    "git_read":        ["terminal"],
    "git_write":       ["terminal"],
    "net_outbound":    ["web"],
    "send_message":    [],           # 由 Runtime 处理
    "create_task":     ["delegation"],
    "delegate_task":   ["delegation"],
}

# Risk level → Hermes approval gate
RISK_TO_HERMES_APPROVAL = {
    RiskLevel.SAFE:     "auto",
    RiskLevel.LOW:      "auto",
    RiskLevel.MEDIUM:   "ask",
    RiskLevel.HIGH:     "require",
    RiskLevel.CRITICAL: "require",
}


# ───────────────────────────────────────────────────────────────────
# Connector Implementation
# ───────────────────────────────────────────────────────────────────


@register_connector_v2("hermes_agent")
class HermesAgentConnector(AgentConnectorV2):
    """
    Hermes Agent Connector — v2 集成。

    将 Multi-agent-IM 的 Soul Profile 注入 Hermes AIAgent，
    让 Agent 拥有 Hermes 的全功能工具集和自主规划能力。

    Hermes 的优势:
      - 70+ 内置工具 (web search, file I/O, terminal, browser, code exec, delegation)
      - Think-Act-Observe 循环 (最多 90 轮)
      - 上下文压缩 + 迭代预算管理
      - 18+ LLM 提供商支持
    """

    def __init__(self):
        self.config: dict[str, Any] = {}
        self._agent_id: str = ""
        self._agent_name: str = ""

    # ── Identity ──────────────────────────────────────────────────

    def connector_name(self) -> str:
        return "hermes_agent"

    def connector_version(self) -> str:
        return "1.0.0"

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self, agent_config: dict[str, Any]) -> None:
        self.config = agent_config
        self._agent_id = agent_config.get("agent_id", "")
        self._agent_name = agent_config.get("agent_name", "")

        if not HERMES_AVAILABLE:
            logger.warning(
                "HermesAgentConnector initialized but Hermes is not installed. "
                "Agent %s will return offline status.", self._agent_id
            )
        else:
            logger.info(
                "HermesAgentConnector initialized: agent=%s model=%s",
                self._agent_id,
                agent_config.get("model", "anthropic/claude-sonnet-4"),
            )

    async def health_check(self) -> bool:
        return HERMES_AVAILABLE

    async def shutdown(self) -> None:
        logger.info("HermesAgentConnector shutdown")

    # ── Capability Inventory ─────────────────────────────────────

    def capability_inventory(self) -> CapabilityInventory:
        inv = CapabilityInventory(
            framework="hermes_agent",
            text_generation=True,
            streaming=True,
            structured_output=False,
            # Hermes 有完整的文件/Shell/Web 能力
            file_read=True,
            file_write=True,
            file_search=True,
            shell_execution=True,
            code_execution=True,
            browser_automation=True,
            git_read=True,
            git_write=True,
            web_search=True,
            web_fetch=True,
            multi_agent_orchestration=False,
            sub_agent_delegation=True,
            human_approval=True,
            max_context_tokens=200000,
            max_output_tokens=16384,
            supports_prompt_caching=HERMES_AVAILABLE,
            supported_tools=[
                "read_file", "write_file", "patch", "search_files",
                "terminal", "web_search", "web_extract",
                "execute_code", "delegate_task", "vision_analyze",
            ],
            max_tools_per_request=70,
        )
        if not HERMES_AVAILABLE:
            inv.extra["status"] = "offline"
            inv.extra["install_hint"] = _deferred_error
        return inv

    def tool_definitions(self) -> list[ToolDefinition]:
        """返回 Hermes 的核心工具定义（简化，完整列表 70+）。"""
        tools = [
            ("read_file", "Read file contents", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
            ("write_file", "Write or create a file", ToolPermission.FILE_WRITE, RiskLevel.HIGH, True),
            ("search_files", "Search files by name/content", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
            ("terminal", "Execute shell commands", ToolPermission.SHELL_EXEC, RiskLevel.HIGH, True),
            ("web_search", "Search the web", ToolPermission.NET_OUTBOUND, RiskLevel.LOW, False),
            ("web_extract", "Extract content from URL", ToolPermission.NET_OUTBOUND, RiskLevel.LOW, False),
            ("execute_code", "Execute code in sandbox", ToolPermission.SHELL_EXEC, RiskLevel.MEDIUM, True),
            ("delegate_task", "Delegate to sub-agent", ToolPermission.DELEGATE_TASK, RiskLevel.MEDIUM, False),
        ]
        return [
            ToolDefinition(
                name=n, description=d, parameters={},
                permission=p, risk_level=r, requires_approval=a,
            )
            for n, d, p, r, a in tools
        ]

    # ── Core: act() ──────────────────────────────────────────────

    async def act(
        self,
        context: ConversationContext,
        soul_profile: Any,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> ActionResult:
        if not HERMES_AVAILABLE:
            return ActionResult(
                text=f"[Hermes Agent is offline. {_deferred_error}]",
                success=False,
                error_message=_deferred_error,
            )

        import time
        t_start = time.monotonic()

        try:
            # ── 1. 构建 AIAgent 配置 ──────────────────────────────
            model = self.config.get("model", "anthropic/claude-sonnet-4")
            api_key = self.config.get("api_key") or os.getenv("ANTHROPIC_API_KEY") or ""

            # 工具集白名单
            tool_permissions = self.config.get("tool_permissions", [])
            if isinstance(tool_permissions, str):
                import json
                tool_permissions = json.loads(tool_permissions) if tool_permissions else []
            enabled_toolsets = self._resolve_toolsets(tool_permissions)

            # Soul Profile → System Message
            system_msg = ""
            if hasattr(soul_profile, 'build_system_prompt'):
                system_msg = soul_profile.build_system_prompt(
                    context={"channel_id": context.channel_id},
                    memories=memory_context.episodic if memory_context else [],
                )

            # ── 2. 构建用户消息 ───────────────────────────────────
            user_message = self._build_user_message(context)

            if event_callback:
                await event_callback(AgentEvent(
                    agent_id=self._agent_id,
                    agent_name=self._agent_name,
                    event_type=AgentEventType.THINKING,
                    payload={"connector": "hermes_agent"},
                ))

            # ── 3. 创建 AIAgent 实例并执行（同步→异步桥接）───────
            def _run_hermes():
                agent = AIAgent(
                    model=model,
                    quiet_mode=True,
                    skip_memory=True,
                    skip_context_files=True,
                    enabled_toolsets=enabled_toolsets if enabled_toolsets else None,
                    max_iterations=30,
                )
                return agent.run_conversation(
                    user_message=user_message,
                )

            # asyncio.to_thread() 避免阻塞 event loop
            result = await asyncio.to_thread(_run_hermes)

            # ── 4. 转换结果 ───────────────────────────────────────
            final_response = result.get("final_response", "") if isinstance(result, dict) else str(result)
            messages_count = len(result.get("messages", [])) if isinstance(result, dict) else 0

            total_ms = (time.monotonic() - t_start) * 1000

            # 构建 memory candidates
            memory_candidates = []
            if len(final_response) > 100:
                memory_candidates.append({
                    "type": "conversation_summary",
                    "content": final_response[:500],
                    "importance": 0.6,
                    "framework": "hermes_agent",
                })

            return ActionResult(
                text=final_response,
                reasoning_trace=f"framework=hermes_agent model={model} messages={messages_count}",
                memory_candidates=memory_candidates,
                total_duration_ms=total_ms,
                rounds=messages_count // 2,  # rough estimate
                success=True,
            )

        except Exception as e:
            logger.error("Hermes act() error: %s", e, exc_info=True)
            return ActionResult(
                text=f"[Hermes Agent 执行出错: {e}]",
                success=False,
                error_message=str(e),
            )

    # ── Core: act_stream() ───────────────────────────────────────

    async def act_stream(
        self,
        context: ConversationContext,
        soul_profile: Any,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        if not HERMES_AVAILABLE:
            yield f"[Hermes Agent is offline. {_deferred_error}]"
            return

        # Hermes 的流式输出通过 to_thread 包装同步调用
        # AIAgent 的迭代器模式不适合逐字流式，所以先生成完整结果再 yield
        import time
        t_start = time.monotonic()

        try:
            model = self.config.get("model", "anthropic/claude-sonnet-4")
            user_message = self._build_user_message(context)

            tool_permissions = self.config.get("tool_permissions", [])
            if isinstance(tool_permissions, str):
                import json
                tool_permissions = json.loads(tool_permissions) if tool_permissions else []
            enabled_toolsets = self._resolve_toolsets(tool_permissions)

            system_msg = ""
            if hasattr(soul_profile, 'build_system_prompt'):
                system_msg = soul_profile.build_system_prompt(
                    context={"channel_id": context.channel_id},
                    memories=memory_context.episodic if memory_context else [],
                )

            def _run():
                agent = AIAgent(
                    model=model,
                    quiet_mode=True,
                    skip_memory=True,
                    skip_context_files=True,
                    enabled_toolsets=enabled_toolsets if enabled_toolsets else None,
                )
                return agent.run_conversation(user_message=user_message)

            result = await asyncio.to_thread(_run)
            final_response = result.get("final_response", "") if isinstance(result, dict) else str(result)
            yield final_response

        except Exception as e:
            yield f"[Hermes Agent error: {e}]"

    # ── Helpers ───────────────────────────────────────────────────

    def _resolve_toolsets(self, permissions: list[str]) -> list[str]:
        """将 Multi-agent-IM 权限列表映射为 Hermes toolsets。"""
        if not permissions:
            return []  # 空 = 全部关闭
        toolsets: set[str] = set()
        for perm in permissions:
            mapped = PERMISSION_TO_HERMES_TOOLSET.get(perm, [])
            toolsets.update(mapped)
        return sorted(toolsets) if toolsets else []

    def _build_user_message(self, context: ConversationContext) -> str:
        """将 ConversationContext 组装为 Hermes 的 user message。"""
        parts: list[str] = []
        for msg in context.messages[-20:]:  # 最近 20 条
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("sender_name", "")
            sender_type = msg.get("sender_type", "human")

            if role == "system":
                continue
            if not content.strip():
                continue

            if name and sender_type == "agent":
                parts.append(f"[{name} (AI)]: {content}")
            elif name:
                parts.append(f"{name}: {content}")
            else:
                parts.append(content)

        return "\n".join(parts)
