"""
MemoryService — 统一记忆管理服务 (v2)。

与第一代的区别:
  v1: 记忆逻辑分散在 reasoning_engine.py + soul_engine/memory.py + agent_service.py
  v2: MemoryService 是独立服务，所有记忆 CRUD + 检索 + 重要性评估集中管理

职责:
  1. 记忆 CRUD（替代直接操作 db.get_memories / db.save_memory）
  2. 语义搜索（pgvector cosine similarity）
  3. 重要性评估（LLM-based + heuristic fallback）
  4. Token 预算管理（四层分级限额）
  5. 定期衰减与清理
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from soul_engine.memory import (
    MemoryTier,
    MemoryType,
    retrieve_episodic_memories,
    semantic_search,
    assess_importance,
    assess_importance_llm,
    MemoryBudget,
)

logger = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """提供给 Connector 的记忆上下文。"""
    # 分层记忆
    core_memories: list[dict[str, Any]]     # 永久记忆
    working_memories: list[dict[str, Any]]  # 项目周期记忆
    buffer_memories: list[dict[str, Any]]   # 近期记忆

    # 语义搜索结果（如果提供了搜索 query）
    semantic_results: list[dict[str, Any]]

    # 总计
    total_tokens_estimate: int = 0

    def all_episodic(self, max_count: int = 30) -> list[dict[str, Any]]:
        """合并所有分层记忆，按重要性排序，返回 top-N。"""
        all_mems = self.core_memories + self.working_memories + self.buffer_memories
        return retrieve_episodic_memories(all_mems, k=max_count)

    def as_snapshot(self):
        """转换为 connector.base.MemorySnapshot 供 v1 接口使用。"""
        from connector.base import MemorySnapshot
        return MemorySnapshot(
            episodic=[
                m.get("content", {})
                for m in self.all_episodic(30)
            ],
            semantic=self.semantic_results,
            relational=[],
        )


class MemoryService:
    """
    统一记忆管理。

    使用方式:
      svc = MemoryService(db)
      ctx = await svc.get_context(agent_id, query="bug fix")
      # 注入到 Connector
      result = await connector.act(..., memory_context=ctx.as_snapshot())
      # 保存对话记忆
      await svc.save_conversation(agent_id, messages, context_meta)
    """

    def __init__(self, db):
        self.db = db
        self.budgets: dict[str, MemoryBudget] = {}

    # ── 检索 ──────────────────────────────────────────────────────

    async def get_context(
        self,
        agent_id: str,
        query: str | None = None,
        max_core: int = 5,
        max_working: int = 10,
        max_buffer: int = 10,
    ) -> MemoryContext:
        """获取 Agent 的完整记忆上下文。"""
        core = await self.db.get_memories(agent_id, MemoryTier.CORE.value, max_core)
        working = await self.db.get_memories(agent_id, MemoryTier.WORKING.value, max_working)
        buffer = await self.db.get_memories(agent_id, MemoryTier.BUFFER.value, max_buffer)

        semantic = []
        if query:
            all_working = working + buffer
            semantic = semantic_search(query, all_working, top_k=5)

        # 粗略 token 估算
        total_chars = sum(
            len(str(m.get("content", ""))) for m in core + working + buffer
        )
        tokens_est = total_chars // 4

        return MemoryContext(
            core_memories=core,
            working_memories=working,
            buffer_memories=buffer,
            semantic_results=semantic,
            total_tokens_estimate=tokens_est,
        )

    async def search(
        self,
        agent_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """语义搜索 Agent 的记忆。"""
        all_mems = await self.db.get_all_memories(agent_id, limit=200)
        return semantic_search(query, all_mems, top_k=top_k)

    # ── 写入 ──────────────────────────────────────────────────────

    async def save_conversation(
        self,
        agent_id: str,
        messages: list[dict[str, Any]],
        context_meta: dict[str, Any] | None = None,
    ) -> str | None:
        """评估并保存一段对话到记忆。

        返回 memory_id，如果重要性不足（被判定为 transient）则返回 None。
        """
        ctx = context_meta or {}

        # 阶段 1: 快速启发式评估
        score = assess_importance(messages, ctx)
        if score < 0.2:
            return None  # transient, don't store

        # 阶段 2: LLM 精确评估（如果可用）
        try:
            llm_result = await assess_importance_llm(messages, ctx)
            tier_name = llm_result.get("tier", "buffer")
            # 映射 tier 名称
            tier_map = {"core": MemoryTier.CORE, "working": MemoryTier.WORKING,
                         "buffer": MemoryTier.BUFFER, "transient": MemoryTier.TRANSIENT}
            tier = tier_map.get(tier_name, MemoryTier.BUFFER)
        except Exception:
            # Fallback to heuristic
            if score >= 0.8:
                tier = MemoryTier.CORE
            elif score >= 0.5:
                tier = MemoryTier.WORKING
            elif score >= 0.3:
                tier = MemoryTier.BUFFER
            else:
                return None

        memory = {
            "type": MemoryType.EPISODIC.value,
            "tier": tier.value,
            "content": {"messages": messages, "context": ctx},
            "importance": score,
            "tags": ctx.get("tags", []),
        }

        mem_id = await self.db.save_memory(agent_id, memory)
        logger.debug("Memory saved: %s tier=%s score=%.2f", mem_id, tier.value, score)
        return mem_id

    async def save_semantic(
        self,
        agent_id: str,
        knowledge: str,
        source: str = "",
        confidence: float = 0.9,
    ) -> str:
        """保存语义记忆（知识条目）。"""
        memory = {
            "type": MemoryType.SEMANTIC.value,
            "tier": MemoryTier.WORKING.value,
            "content": {
                "knowledge": knowledge,
                "source": source,
                "confidence": confidence,
            },
            "importance": 0.7,
            "tags": ["knowledge", source.replace(".md", "") if source else "manual"],
        }
        return await self.db.save_memory(agent_id, memory)

    # ── 管理 ──────────────────────────────────────────────────────

    async def promote(self, memory_id: str, target_tier: MemoryTier) -> None:
        """将记忆提升到更高级别。"""
        await self.db.update_memory_tier(memory_id, target_tier.value)
        logger.info("Memory %s promoted to %s", memory_id, target_tier.value)

    async def archive(self, memory_id: str) -> None:
        """归档记忆。"""
        await self.db.update_memory_tier(memory_id, MemoryTier.ARCHIVED.value)

    async def forget(self, memory_id: str) -> None:
        """删除记忆。"""
        await self.db.delete_memory(memory_id)

    async def list_memories(
        self,
        agent_id: str,
        tier: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出 Agent 的记忆（支持按 tier 筛选）。"""
        if tier:
            return await self.db.get_memories(agent_id, tier, limit)
        return await self.db.get_all_memories(agent_id, limit=limit)

    async def apply_decay(self, agent_id: str) -> int:
        """对 Agent 的 Buffer 层记忆应用衰减。返回衰减的记忆数。"""
        from soul_engine.memory import apply_decay
        from datetime import datetime, timezone

        buffer_mems = await self.db.get_memories(agent_id, MemoryTier.BUFFER.value, 500)
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for mem in buffer_mems:
            decayed = apply_decay(mem, now)
            if decayed.get("importance", 0.5) < 0.15:
                await self.archive(mem["id"])
                count += 1
        return count
