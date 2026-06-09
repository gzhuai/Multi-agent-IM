"""
EventBus — Agent 事件总线 (v2)。

基于 Redis Pub/Sub 实现 Agent 实时事件的发布与订阅。
IM Core 的 WebSocket Hub 订阅 Redis channel，将事件推送给客户端。

职责:
  1. 发布 Agent 执行过程中的实时事件
  2. 客户端通过 WebSocket 订阅 channel:{id} 和 agent:{id} 接收事件
  3. 支持事件持久化（审计用，可选）

使用方式:
  bus = EventBus(redis_client)
  await bus.publish(AgentEvent(...))
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from connector.base_v2 import AgentEventType

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# 事件数据类 (轻量版，与 connector/base_v2.py 中的 AgentEvent 互补)
# ───────────────────────────────────────────────────────────────────


@dataclass
class AgentEvent:
    """Agent 实时事件 — EventBus 的消息单元。"""
    agent_id: str
    agent_name: str
    event_type: AgentEventType
    task_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp_ms: int = 0

    def __post_init__(self):
        if not self.timestamp_ms:
            self.timestamp_ms = int(time.time() * 1000)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 Redis message JSON。"""
        return {
            "type": "agent_event",
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "event": self.event_type.value,
            "task_id": self.task_id,
            "payload": self.payload,
            "ts": self.timestamp_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentEvent":
        return cls(
            agent_id=data.get("agent_id", ""),
            agent_name=data.get("agent_name", ""),
            event_type=AgentEventType(data.get("event", "agent_started")),
            task_id=data.get("task_id", ""),
            payload=data.get("payload", {}),
            timestamp_ms=data.get("ts", 0),
        )


# ───────────────────────────────────────────────────────────────────
# Redis 客户端接口（最小协议 — 不依赖具体 Redis 实现）
# ───────────────────────────────────────────────────────────────────


class RedisPublisher(Protocol):
    """Redis Pub/Sub 发布者的最小协议。"""

    async def publish(self, channel: str, message: str) -> int:
        """发布消息到 channel，返回收到消息的订阅者数。"""
        ...


# ───────────────────────────────────────────────────────────────────
# EventBus
# ───────────────────────────────────────────────────────────────────


class EventBus:
    """
    Agent 事件总线。

    Redis channel 设计:
      agent:{agent_id}:events   → 单个 Agent 的执行事件
      channel:{channel_id}:events → 频道内所有 Agent 的事件
    """

    def __init__(self, redis: RedisPublisher | None = None):
        self.redis = redis
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        logger.info("EventBus initialized (redis=%s)", "yes" if redis else "no (offline mode)")

    # ── 发布 ──────────────────────────────────────────────────────

    async def publish(self, event: AgentEvent) -> None:
        """发布事件到相关 channels。"""
        msg = event.to_json()

        channels = [
            f"agent:{event.agent_id}:events",
        ]
        # 如果有 channel context，也发到 channel 事件流
        channel_id = event.payload.get("channel_id")
        if channel_id:
            channels.append(f"channel:{channel_id}:events")

        if self.redis:
            for ch in channels:
                try:
                    await self.redis.publish(ch, msg)
                except Exception as e:
                    logger.warning("Failed to publish to %s: %s", ch, e)
        else:
            logger.debug("Event (offline): %s", event.event_type.value)

    # ── 便捷发布方法 ──────────────────────────────────────────────

    async def started(self, agent_id: str, agent_name: str, task_id: str = "",
                      channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.AGENT_STARTED,
            task_id=task_id, payload={"channel_id": channel_id},
        ))

    async def thinking(self, agent_id: str, agent_name: str, task_id: str = "",
                       channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.THINKING,
            task_id=task_id, payload={"channel_id": channel_id},
        ))

    async def thought_chunk(self, agent_id: str, agent_name: str,
                            text: str, task_id: str = "",
                            channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.THOUGHT_CHUNK,
            task_id=task_id,
            payload={"text": text, "channel_id": channel_id},
        ))

    async def tool_executing(self, agent_id: str, agent_name: str,
                             tool_name: str, tool_params: dict[str, Any],
                             task_id: str = "", channel_id: str = "",
                             sandbox_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.TOOL_EXECUTING,
            task_id=task_id,
            payload={
                "tool_name": tool_name,
                "tool_params": _sanitize_params(tool_params),
                "channel_id": channel_id,
                "sandbox_id": sandbox_id,
            },
        ))

    async def tool_result(self, agent_id: str, agent_name: str,
                          tool_name: str, success: bool,
                          summary: str, task_id: str = "",
                          channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.TOOL_RESULT,
            task_id=task_id,
            payload={
                "tool_name": tool_name,
                "success": success,
                "summary": summary[:500],
                "channel_id": channel_id,
            },
        ))

    async def tool_error(self, agent_id: str, agent_name: str,
                         tool_name: str, error: str, task_id: str = "",
                         channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.TOOL_ERROR,
            task_id=task_id,
            payload={
                "tool_name": tool_name,
                "error": error[:500],
                "channel_id": channel_id,
            },
        ))

    # ── 审批相关 ──────────────────────────────────────────────────

    async def approval_needed(self, agent_id: str, agent_name: str,
                              approval_id: str, tool_name: str,
                              action_description: str, risk_level: str,
                              tool_params: dict[str, Any],
                              timeout_s: int = 300,
                              task_id: str = "", channel_id: str = "") -> str:
        """推送审批请求。返回 approval_id。"""
        self._pending_approvals[approval_id] = {
            "agent_id": agent_id,
            "status": "PENDING",
            "created_at": time.time(),
            "timeout_s": timeout_s,
        }
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.APPROVAL_NEEDED,
            task_id=task_id,
            payload={
                "approval_id": approval_id,
                "tool_name": tool_name,
                "action_description": action_description,
                "risk_level": risk_level,
                "tool_params": _sanitize_params(tool_params),
                "timeout_seconds": timeout_s,
                "channel_id": channel_id,
            },
        ))
        return approval_id

    async def resolve_approval(self, approval_id: str, approved: bool,
                               comment: str = "") -> dict[str, Any] | None:
        """处理审批结果。返回 pending approval 数据，如果已过期则返回 None。"""
        pending = self._pending_approvals.pop(approval_id, None)
        if pending is None:
            return None

        elapsed = time.time() - pending["created_at"]
        if elapsed > pending["timeout_s"]:
            pending["status"] = "TIMEOUT"
            return None  # 超时

        pending["status"] = "APPROVED" if approved else "DENIED"
        pending["resolved_at"] = time.time()
        pending["comment"] = comment
        return pending

    async def done(self, agent_id: str, agent_name: str, task_id: str = "",
                   channel_id: str = "", summary: str = "",
                   success: bool = True) -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.AGENT_DONE,
            task_id=task_id,
            payload={
                "channel_id": channel_id,
                "summary": summary[:500],
                "success": success,
            },
        ))

    async def error(self, agent_id: str, agent_name: str,
                    error_message: str, task_id: str = "",
                    channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.AGENT_ERROR,
            task_id=task_id,
            payload={
                "channel_id": channel_id,
                "error": error_message[:1000],
            },
        ))

    async def progress(self, agent_id: str, agent_name: str,
                       current: int, total: int, message: str,
                       task_id: str = "", channel_id: str = "") -> None:
        await self.publish(AgentEvent(
            agent_id=agent_id, agent_name=agent_name,
            event_type=AgentEventType.PROGRESS,
            task_id=task_id,
            payload={
                "channel_id": channel_id,
                "current_step": current,
                "total_steps": total,
                "message": message,
            },
        ))


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────

def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """安全化工具参数 — 去除敏感值（API key 等）。"""
    sensitive_keys = {"api_key", "password", "token", "secret", "authorization"}
    sanitized = {}
    for k, v in params.items():
        if k.lower() in sensitive_keys:
            sanitized[k] = "***"
        elif isinstance(v, str) and len(v) > 500:
            sanitized[k] = v[:500] + "..."
        else:
            sanitized[k] = v
    return sanitized
