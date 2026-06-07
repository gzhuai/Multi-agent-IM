"""
Memory retrieval, decay, lifecycle management, and LLM-based importance assessment.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
        now = now or datetime.now(timezone.utc)
        return (now - self.created_at) > self.ttl if self.created_at else False


# ── Memory retrieval ──────────────────────────────────────────

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


def semantic_search(
    query: str,
    memories: list[dict],
    top_k: int = 10,
    similarity_weight: float = 0.6,
    importance_weight: float = 0.4,
) -> list[dict]:
    """
    Rank memories by combined semantic similarity + importance.
    Falls back to importance-only if embeddings aren't available.
    """
    if not memories:
        return []

    # Try to get embedding for query
    query_emb = generate_embedding(query)
    if query_emb is None:
        # Fallback: importance-only ranking
        return retrieve_episodic_memories(memories, top_k)

    import math

    scored = []
    for m in memories:
        mem_emb = m.get("_embedding")
        if mem_emb is None:
            # Memories without embeddings get importance-only score
            scored.append((importance_weight * m.get("importance", 0.5), m))
            continue

        # Cosine similarity
        dot = sum(a * b for a, b in zip(query_emb, mem_emb))
        norm_q = math.sqrt(sum(a * a for a in query_emb))
        norm_m = math.sqrt(sum(b * b for b in mem_emb))
        similarity = dot / (norm_q * norm_m + 1e-10)

        importance = m.get("importance", 0.5)
        score = similarity_weight * similarity + importance_weight * importance
        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:top_k]]


# ── Embedding generation ──────────────────────────────────────

_embedding_cache: dict[str, list[float]] = {}

def generate_embedding(text: str, model: str = "text-embedding-3-small") -> Optional[list[float]]:
    """
    Generate embedding vector for text using the LLM API.
    Uses OpenAI-compatible /v1/embeddings endpoint.
    Falls back gracefully if API is unavailable.
    """
    if not text or not text.strip():
        return None

    cache_key = f"{model}:{hash(text)}"
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]

    try:
        import os, json
        import urllib.request

        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY", "")
        if not api_key:
            return None

        base_url = os.getenv("EMBEDDING_BASE_URL", "https://api.deepseek.com")
        if "deepseek" in base_url:
            # DeepSeek doesn't have embedding API yet — use a local heuristic
            # In production, use text-embedding-3-small from OpenAI or voyage
            return _heuristic_embedding(text)

        data = json.dumps({"model": model, "input": text}).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/embeddings",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        emb = resp["data"][0]["embedding"]
        _embedding_cache[cache_key] = emb
        return emb
    except Exception:
        return _heuristic_embedding(text)


def _heuristic_embedding(text: str, dims: int = 256) -> list[float]:
    """
    Fallback: generate a pseudo-embedding from keyword overlap.
    Not as good as real embeddings, but enables semantic search to work.
    """
    import hashlib
    # Use hash-based pseudo-vector for deterministic similarity
    words = text.lower().split()
    vec = [0.0] * dims
    for i, word in enumerate(words):
        h = hashlib.md5(word.encode()).digest()
        for j in range(min(16, dims)):
            idx = (i * 7 + j * 13 + h[j % 16]) % dims
            vec[idx] += 1.0
    # Normalize
    import math
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# ── Memory decay ──────────────────────────────────────────────

def apply_decay(memory: dict, current_time: str) -> dict:
    """Reduce importance based on time since last access."""
    import copy
    m = copy.deepcopy(memory)
    last = m.get("last_accessed", m.get("created_at", current_time))
    if last and last < current_time:
        m["importance"] = m.get("importance", 0.5) * 0.95
    m["last_accessed"] = current_time
    return m


# ── LLM-based importance assessment ───────────────────────────

async def assess_importance_llm(messages: list[dict], context: dict) -> dict:
    """
    Use LLM to evaluate conversation importance for memory retention.
    Returns: {"score": 0-1, "tier": "core|working|buffer|transient", "reasoning": str}
    """
    text = " ".join(m.get("content", "") for m in messages)
    if len(text) < 20:
        return {"score": 0.0, "tier": "transient", "reasoning": "too short"}

    prompt = f"""Rate the importance of this conversation for long-term memory (0.0-1.0):

{text[:600]}

Reply with ONLY a JSON object: {{"score": <0-1>, "tier": "<core|working|buffer|transient>", "reasoning": "<one sentence>"}}"""

    try:
        import os, json
        import httpx

        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY", "")
        if not api_key:
            return assess_importance_fallback(messages, context)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.1,
                },
            )
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            # Extract JSON
            if "{" in raw and "}" in raw:
                raw = raw[raw.index("{"):raw.rindex("}")+1]
            return json.loads(raw)
    except Exception:
        return assess_importance_fallback(messages, context)


def assess_importance(messages: list[dict], context: dict) -> float:
    """Synchronous fallback: heuristic-based importance (used when LLM unavailable)."""
    result = assess_importance_fallback(messages, context)
    return result["score"]


def assess_importance_fallback(messages: list[dict], context: dict) -> dict:
    """Heuristic importance assessment — keyword-based."""
    score = 0.3
    text = " ".join(m.get("content", "") for m in messages)

    if any(kw in text for kw in ["决策", "决定", "路线", "战略", "预算", "decision", "roadmap"]):
        score += 0.3
    if any(kw in text for kw in ["上线", "发布", "deadline", "里程碑", "release", "launch"]):
        score += 0.2
    if any(kw in text for kw in ["bug", "问题", "阻塞", "故障", "error", "blocked", "incident"]):
        score += 0.15
    if context.get("has_human_review"):
        score += 0.1
    if context.get("wake"):
        score += 0.05

    score = min(score, 1.0)

    if score >= 0.8:
        tier = "core"
    elif score >= 0.5:
        tier = "working"
    elif score >= 0.3:
        tier = "buffer"
    else:
        tier = "transient"

    return {"score": score, "tier": tier, "reasoning": "heuristic keyword match"}


# ── Token Budget ──────────────────────────────────────────────

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
