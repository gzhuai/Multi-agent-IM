"""
ConnectorRouter — v2 请求分发器 (Phase 1)。

职责:
  1. 根据 agent.connector_type_v2 将请求分发到 v2 Connector 或旧 ReasoningEngine
  2. 在 v2 Connector 未实现时，全部回退到 ReasoningEngine (双轨兼容)
  3. 记录路由决策到日志（供调试和迁移跟踪）

双轨策略:
  - connector_type_v2 为 NULL / 空 / 'openai_compatible' / 'claude_code' → 旧路径
  - connector_type_v2 为 'anthropic_agent' / 'hermes_agent' 等且在 registry → 新路径
  - connector_type_v2 为新值但未在 registry → 旧路径 + Warning 日志

Phase 1 状态:
  所有注册的 v2 Connector 均为 None（Phase 2 起逐步实现），
  因此全部走旧路径，功能完全不变。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.db import Database
from agent_runtime.agent_service import AgentService
from soul_serializer import SoulSerializer
from memory_service import MemoryService
from event_bus import EventBus
from sandbox_manager import SandboxManager

from connector.base import (
    ConversationContext,
    MemorySnapshot,
)
from connector.base_v2 import (
    AgentConnectorV2,
    AgentEvent,
    AgentEventType,
    ActionResult,
    CapabilityInventory,
    CONNECTOR_REGISTRY_V2,
    get_connector_v2,
)

# Trigger @register_connector_v2 for all v2 connectors
import connector.anthropic_agent  # noqa: F401
import connector.hermes_agent  # noqa: F401
import workflow_engine  # noqa: F401

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """路由决策记录。"""
    agent_id: str
    connector_type_v2: str
    route: str  # "v2:anthropic_agent" | "v1:reasoning_engine" | "v1:fallback"
    reason: str


@dataclass
class RoutingResult:
    """路由执行结果 — 统一 v1/v2 的返回格式。"""
    text: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    reasoning_trace: str = ""
    memory_saved: bool = False
    tool_executions: list[dict[str, Any]] = field(default_factory=list)
    file_changes: list[dict[str, Any]] = field(default_factory=list)
    route_decision: RouteDecision | None = None
    error: str = ""


class ConnectorRouter:
    """
    请求分发器 — Phase 1 实现双轨路由。

    使用方式:
      router = ConnectorRouter(db, reasoning_engine)
      result = await router.route(agent_id, channel_id, messages, participants)

    扩展方式 (Phase 2+):
      在 connector/__init__.py 中注册 v2 Connector:
        from connector.anthropic_agent import AnthropicAgentConnector  # @register_connector_v2
      此后 ConnectorRouter 自动发现并路由到该 Connector。
    """

    def __init__(
        self,
        db: Database,
        reasoning_engine,  # ReasoningEngine (deprecated, kept for backward compat)
        event_bus: EventBus | None = None,
        sandbox_manager: SandboxManager | None = None,
    ):
        self.db = db
        self.reasoning_engine = reasoning_engine
        self.agent_service = AgentService(db)
        self.soul_serializer = SoulSerializer()
        self.memory_service = MemoryService(db)
        self.event_bus = event_bus or EventBus()
        self.sandbox_manager = sandbox_manager or SandboxManager(mode="local")

        # v2 Connector 实例缓存 (connector_name → instance)
        self._connectors: dict[str, AgentConnectorV2] = {}

        logger.info(
            "ConnectorRouter initialized: v2 connectors=%s",
            list(CONNECTOR_REGISTRY_V2.keys()),
        )

    # ── 路由 ──────────────────────────────────────────────────────

    async def route(
        self,
        agent_id: str,
        channel_id: str,
        messages: list[dict[str, Any]],
        participants: list[dict[str, Any]] | None = None,
    ) -> RoutingResult:
        """核心路由方法。"""
        # 1. 获取 Agent
        agent_data = await self.agent_service.get_agent(agent_id)
        if not agent_data:
            return RoutingResult(text="[Agent not found]", error="agent not found")

        # 2. 决定路由
        decision = self._decide_route(agent_data)

        # 3. 执行
        if decision.route.startswith("v2:"):
            return await self._route_v2(agent_data, decision, channel_id, messages, participants)
        else:
            return await self._route_v1(agent_data, decision, channel_id, messages, participants)

    async def route_wake(
        self,
        agent_id: str,
        channel_id: str,
        participants: list[dict[str, Any]] | None = None,
    ) -> RoutingResult:
        """路由自主唤醒请求。"""
        agent_data = await self.agent_service.get_agent(agent_id)
        if not agent_data:
            return RoutingResult(text="", error="agent not found")

        decision = self._decide_route(agent_data)

        if decision.route.startswith("v2:"):
            # v2 wake — create wake-specific context
            import datetime
            now = datetime.datetime.now().strftime("%H:%M")
            wake_msg = {
                "role": "user",
                "content": f"[System wake at {now}]",
                "sender_name": "system",
            }
            return await self._route_v2(agent_data, decision, channel_id, [wake_msg], participants)
        else:
            # v1 wake — delegate to ReasoningEngine
            result = await self.reasoning_engine.process_wake(
                agent_id=agent_id,
                channel_id=channel_id,
                participants=participants or [],
            )
            return RoutingResult(
                text=result.text,
                actions=result.actions,
                reasoning_trace=result.reasoning_trace,
                memory_saved=result.memory_saved,
                route_decision=decision,
            )

    async def route_stream(
        self,
        agent_id: str,
        channel_id: str,
        messages: list[dict[str, Any]],
        participants: list[dict[str, Any]] | None = None,
    ):
        """流式路由 — 目前全部走 v1 流式。"""
        agent_data = await self.agent_service.get_agent(agent_id)
        if not agent_data:
            yield "[Agent not found]"
            return

        decision = self._decide_route(agent_data)

        if decision.route.startswith("v2:"):
            # v2 流式 — 尚未实现，回退
            logger.warning("v2 streaming not implemented, falling back to v1")
            connector_name = decision.route.split(":", 1)[1]
            connector = await self._get_connector(connector_name, agent_data)
            if connector:
                try:
                    async for chunk in connector.act_stream(
                        context=self._build_context(channel_id, messages, participants),
                        soul_profile=self.soul_serializer.build_from_db(agent_data),
                        memory_context=(await self.memory_service.get_context(agent_id)).as_snapshot(),
                        event_callback=None,
                    ):
                        yield chunk
                    return
                except NotImplementedError:
                    pass  # fall through to v1

        # v1 streaming — delegate
        async for chunk in self.reasoning_engine.process_message_stream(
            agent_id=agent_id,
            channel_id=channel_id,
            messages=messages,
            participants=participants or [],
        ):
            yield chunk

    # ── 路由决策 ──────────────────────────────────────────────────

    def _decide_route(self, agent_data: dict[str, Any]) -> RouteDecision:
        """根据 agent 配置决定走 v1 还是 v2。"""
        agent_id = agent_data.get("id", "unknown")
        connector_v2 = (agent_data.get("connector_type_v2") or "").strip()

        # 未设置 v2 类型 → 旧路径
        if not connector_v2:
            return RouteDecision(
                agent_id=agent_id,
                connector_type_v2="",
                route="v1:reasoning_engine",
                reason="connector_type_v2 not set",
            )

        # 旧的 connector_type 混同 → 旧路径
        if connector_v2 in ("openai_compatible", "claude_code"):
            return RouteDecision(
                agent_id=agent_id,
                connector_type_v2=connector_v2,
                route="v1:reasoning_engine",
                reason=f"legacy connector_type_v2='{connector_v2}'",
            )

        # v2 Connector 是否已注册
        if connector_v2 in CONNECTOR_REGISTRY_V2:
            return RouteDecision(
                agent_id=agent_id,
                connector_type_v2=connector_v2,
                route=f"v2:{connector_v2}",
                reason=f"v2 connector '{connector_v2}' found in registry",
            )

        # v2 值但未注册 → 回退 + 警告
        logger.warning(
            "Agent %s has connector_type_v2='%s' but no such connector is registered. "
            "Available: %s. Falling back to v1.",
            agent_id, connector_v2, list(CONNECTOR_REGISTRY_V2.keys()),
        )
        return RouteDecision(
            agent_id=agent_id,
            connector_type_v2=connector_v2,
            route="v1:fallback",
            reason=f"unregistered connector '{connector_v2}'",
        )

    # ── v1 执行 (旧路径) ──────────────────────────────────────────

    async def _route_v1(
        self,
        agent_data: dict[str, Any],
        decision: RouteDecision,
        channel_id: str,
        messages: list[dict[str, Any]],
        participants: list[dict[str, Any]] | None,
    ) -> RoutingResult:
        """走旧 ReasoningEngine（全功能，不变）。"""
        result = await self.reasoning_engine.process_message(
            agent_id=decision.agent_id,
            channel_id=channel_id,
            messages=messages,
            participants=participants or [],
        )
        return RoutingResult(
            text=result.text,
            actions=result.actions,
            reasoning_trace=result.reasoning_trace,
            memory_saved=result.memory_saved,
            route_decision=decision,
        )

    # ── v2 执行 (新路径) ──────────────────────────────────────────

    async def _route_v2(
        self,
        agent_data: dict[str, Any],
        decision: RouteDecision,
        channel_id: str,
        messages: list[dict[str, Any]],
        participants: list[dict[str, Any]] | None,
    ) -> RoutingResult:
        """走 v2 Connector（新路径）。"""
        connector_name = decision.route.split(":", 1)[1]

        try:
            connector = await self._get_connector(connector_name, agent_data)
            if connector is None:
                logger.error("Failed to initialize v2 connector '%s', falling back to v1", connector_name)
                return await self._route_v1(agent_data, decision, channel_id, messages, participants)

            # 构建 Soul Profile
            soul = self.soul_serializer.build_from_db(agent_data)

            # 检索记忆
            mem_ctx = await self.memory_service.get_context(decision.agent_id)

            # 构建对话上下文
            context = self._build_context(channel_id, messages, participants)

            # 事件回调 (Phase 1: 暂时为 None，后续连接 EventBus)
            async def on_event(event: AgentEvent):
                await self.event_bus.publish(event)

            # 更新状态
            await self.db.update_agent_status(decision.agent_id, "THINKING")

            try:
                import time
                t0 = time.monotonic()

                # 执行
                result: ActionResult = await connector.act(
                    context=context,
                    soul_profile=soul,
                    memory_context=mem_ctx.as_snapshot(),
                    event_callback=on_event,
                )

                elapsed_ms = (time.monotonic() - t0) * 1000

                # 保存对话记忆
                memory_saved = False
                all_messages = messages + [{"role": "assistant", "content": result.text}]
                mem_id = await self.memory_service.save_conversation(
                    decision.agent_id,
                    all_messages,
                    {"channel_id": channel_id},
                )
                if mem_id:
                    memory_saved = True

                logger.info(
                    "v2 route success: agent=%s connector=%s duration=%.0fms "
                    "tools=%d rounds=%d tokens=%d",
                    decision.agent_id, connector_name, elapsed_ms,
                    len(result.tool_executions), result.rounds, result.tokens_used,
                )

                return RoutingResult(
                    text=result.text,
                    actions=[],  # v2 不再使用旧 actions 字段
                    reasoning_trace=result.reasoning_trace,
                    memory_saved=memory_saved,
                    tool_executions=[
                        {
                            "tool_name": t.tool_name,
                            "success": t.success,
                            "summary": t.result_summary,
                            "duration_ms": t.duration_ms,
                        }
                        for t in result.tool_executions
                    ],
                    file_changes=[
                        {
                            "path": f.path,
                            "operation": f.operation,
                            "diff": f.diff,
                        }
                        for f in result.file_changes
                    ],
                    route_decision=decision,
                )

            finally:
                await self.db.update_agent_status(decision.agent_id, "IDLE")

        except Exception as e:
            logger.error(
                "v2 route error for agent %s: %s", decision.agent_id, e, exc_info=True
            )
            return RoutingResult(
                text=f"[Agent reasoning unavailable: {e}]",
                route_decision=decision,
                error=str(e),
            )

    # ── Connector 管理 ────────────────────────────────────────────

    async def _get_connector(
        self, name: str, agent_data: dict[str, Any]
    ) -> AgentConnectorV2 | None:
        """获取或创建 v2 Connector 实例。"""
        agent_id = agent_data.get("id", "")

        # 缓存 key: connector_name + agent_id (每个 Agent 独立配置)
        cache_key = f"{name}:{agent_id}"

        if cache_key in self._connectors:
            return self._connectors[cache_key]

        try:
            connector_cls = get_connector_v2(name)
        except ValueError:
            logger.error("Unknown v2 connector: %s", name)
            return None

        connector = connector_cls()

        # 构建 connector config
        agent_cfg = agent_data.get("connector_config", {})
        tool_permissions = agent_data.get("tool_permissions", [])
        sandbox_config = agent_data.get("sandbox_config", {})
        if isinstance(tool_permissions, str):
            import json
            tool_permissions = json.loads(tool_permissions)
        if isinstance(sandbox_config, str):
            import json
            sandbox_config = json.loads(sandbox_config)

        config = {
            "agent_id": agent_id,
            "agent_name": agent_data.get("name", ""),
            "model": agent_cfg.get("model") or os.getenv("LLM_MODEL", ""),
            "api_key": agent_cfg.get("api_key") or "",
            "base_url": agent_cfg.get("base_url") or "",
            "tool_permissions": tool_permissions if isinstance(tool_permissions, list) else [],
            "sandbox_config": sandbox_config,
            **agent_cfg,
        }

        try:
            await connector.initialize(config)
            self._connectors[cache_key] = connector
            logger.info("v2 connector initialized: %s for agent %s", name, agent_id)
            return connector
        except Exception as e:
            logger.error("Failed to initialize v2 connector '%s': %s", name, e)
            return None

    # ── Helpers ───────────────────────────────────────────────────

    def _build_context(
        self,
        channel_id: str,
        messages: list[dict[str, Any]],
        participants: list[dict[str, Any]] | None,
    ) -> ConversationContext:
        """构建 ConversationContext。"""
        return ConversationContext(
            channel_id=channel_id,
            messages=messages,
            participants=participants or [],
            mentioned=True,
        )

    # ── 管理 ──────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """关闭所有 v2 Connector。"""
        for key, connector in self._connectors.items():
            try:
                await connector.shutdown()
                logger.info("v2 connector shutdown: %s", key)
            except Exception as e:
                logger.warning("Error shutting down v2 connector %s: %s", key, e)
        self._connectors.clear()

    def route_stats(self) -> dict[str, int]:
        """返回路由统计（按 connector type 分组的 Agent 数量）。"""
        # 此方法为异步辅助，调用方需在 async context 中
        return {
            "v2_connectors_loaded": len(self._connectors),
            "v2_connectors_registered": len(CONNECTOR_REGISTRY_V2),
        }
