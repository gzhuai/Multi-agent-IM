"""
Memory retrieval, decay, and lifecycle management.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class MemoryTier(str, Enum):
    CORE = "core"
    WORKING = "working"
    BUFFER = "buffer"
    ARCHIVED = "archived"
    TRANSIENT = "transient"


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONAL = "relational"


@dataclass
class Memory:
    id: str = ""
    agent_id: str = ""
    type: MemoryType = MemoryType.EPISODIC
    tier: MemoryTier = MemoryTier.BUFFER
    content: dict = field(default_factory=dict)
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    ttl: Optional[timedelta] = None
    project_id: Optional[str] = None
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if self.ttl is None:
            return False
        now = now or datetime.utcnow()
        return (now - self.created_at) > self.ttl if self.created_at else False


def retrieve_episodic_memories(
    memories: list[dict],
    k: int = 10,
    recency_weight: float = 0.4,
    importance_weight: float = 0.6,
) -> list[dict]:
    """Sort episodic memories by weighted score and return top-k."""
    if not memories:
        return []
    scored = []
    for m in memories:
        importance = m.get("importance", 0.5)
        scored.append((importance_weight * importance, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:k]]


def apply_decay(memory: dict, current_time: str) -> dict:
    """Reduce importance based on time since last access."""
    import copy
    m = copy.deepcopy(memory)
    last = m.get("last_accessed", m.get("created_at", current_time))
    if last and last < current_time:
        m["importance"] = m.get("importance", 0.5) * 0.95
    m["last_accessed"] = current_time
    return m


def assess_importance(messages: list[dict], context: dict) -> float:
    """
    Evaluate how important a conversation is for memory retention.

    Returns a score 0-1. Score ≥ 0.5 → Working, ≥ 0.8 → Core, < 0.3 → discard.
    This is a heuristic stub; Phase 4 replaces it with an LLM-based assessment.
    """
    score = 0.3  # base

    text = " ".join(m.get("content", "") for m in messages)

    # Heuristics for importance
    if any(kw in text for kw in ["决策", "决定", "路线", "战略", "预算"]):
        score += 0.3
    if any(kw in text for kw in ["上线", "发布", "deadline", "里程碑"]):
        score += 0.2
    if any(kw in text for kw in ["bug", "问题", "阻塞", "故障"]):
        score += 0.15
    if context.get("has_human_review"):
        score += 0.1

    return min(score, 1.0)


class MemoryBudget:
    """Tracks token usage across memory tiers for a single agent."""

    def __init__(self, core: int = 10000, working: int = 20000, buffer: int = 10000):
        self.budget = {"core": core, "working": working, "buffer": buffer}
        self.used = {"core": 0, "working": 0, "buffer": 0}

    def can_fit(self, tier: str, token_count: int) -> bool:
        return self.used.get(tier, 0) + token_count <= self.budget.get(tier, 0)

    def reserve(self, tier: str, token_count: int) -> bool:
        if self.can_fit(tier, token_count):
            self.used[tier] += token_count
            return True
        return False

    def remaining(self, tier: str) -> int:
        return self.budget.get(tier, 0) - self.used.get(tier, 0)

    def reset(self):
        for tier in self.used:
            self.used[tier] = 0
