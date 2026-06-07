"""
Database access layer for agents, memories, and skills.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from agent_runtime.config import DatabaseConfig


class Database:
    def __init__(self, cfg: DatabaseConfig):
        self.engine = create_async_engine(cfg.dsn, echo=False, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self):
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.session_factory()

    # ============================================================
    # Agents
    # ============================================================

    async def create_agent(self, data: dict) -> dict:
        agent_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        async with self.session() as sess:
            await sess.execute(text("""
                INSERT INTO agents (id, organization_id, name, display_name, role,
                    department, level, status, identity, persona, value_system,
                    connector_type, connector_config, created_at, updated_at)
                VALUES (:id, :org_id, :name, :display_name, :role, :department,
                    :level, 'OFFLINE', :identity, :persona, :value_system,
                    :conn_type, :conn_config, :now, :now)
            """), {
                "id": agent_id,
                "org_id": data.get("organization_id", "default"),
                "name": data["name"],
                "display_name": data.get("display_name", data["name"]),
                "role": data.get("role", ""),
                "department": data.get("department", ""),
                "level": data.get("level", 1),
                "identity": json.dumps(data.get("identity", {})),
                "persona": json.dumps(data.get("persona", {})),
                "value_system": json.dumps(data.get("value_system", {})),
                "conn_type": data.get("connector_type", "claude_code"),
                "conn_config": json.dumps(data.get("connector_config", {})),
                "now": now,
            })
            await sess.commit()

        return {"id": agent_id, **data, "status": "OFFLINE"}

    async def get_agent(self, agent_id: str) -> Optional[dict]:
        async with self.session() as sess:
            result = await sess.execute(text("""
                SELECT id, organization_id, name, display_name, role, department,
                       level, status, identity, persona, value_system,
                       connector_type, connector_config, created_at
                FROM agents WHERE id = :id
            """), {"id": agent_id})
            row = result.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "organization_id": row[1],
                "name": row[2],
                "display_name": row[3],
                "role": row[4],
                "department": row[5],
                "level": row[6],
                "status": row[7],
                "identity": row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}"),
                "persona": row[9] if isinstance(row[9], dict) else json.loads(row[9] or "{}"),
                "value_system": row[10] if isinstance(row[10], dict) else json.loads(row[10] or "{}"),
                "connector_type": row[11],
                "connector_config": row[12] if isinstance(row[12], dict) else json.loads(row[12] or "{}"),
                "created_at": row[13],
            }

    async def update_agent_connector(self, agent_id: str, connector_type: str, connector_config: dict) -> None:
        async with self.session() as sess:
            await sess.execute(text("""
                UPDATE agents SET connector_type = :ct, connector_config = :cfg::jsonb,
                    updated_at = :now WHERE id = :id
            """), {
                "id": agent_id, "ct": connector_type,
                "cfg": json.dumps(connector_config),
                "now": datetime.now(timezone.utc),
            })
            await sess.commit()

    async def update_agent_status(self, agent_id: str, status: str) -> None:
        async with self.session() as sess:
            await sess.execute(text("""
                UPDATE agents SET status = :status, updated_at = :now WHERE id = :id
            """), {"id": agent_id, "status": status, "now": datetime.now(timezone.utc)})
            await sess.commit()

    async def list_agents(self, org_id: str = "default") -> list[dict]:
        async with self.session() as sess:
            result = await sess.execute(text("""
                SELECT id, name, display_name, role, department, status, created_at
                FROM agents WHERE organization_id = :org_id ORDER BY created_at DESC
            """), {"org_id": org_id})
            return [
                {"id": r[0], "name": r[1], "display_name": r[2], "role": r[3],
                 "department": r[4], "status": r[5], "created_at": r[6].isoformat()}
                for r in result.fetchall()
            ]

    # ============================================================
    # Memories
    # ============================================================

    async def save_memory(self, agent_id: str, memory: dict) -> str:
        mem_id = uuid.uuid4().hex
        async with self.session() as sess:
            await sess.execute(text("""
                INSERT INTO agent_memories (id, agent_id, type, tier, content,
                    importance, tags, created_at)
                VALUES (:id, :agent_id, :type, :tier, :content, :importance,
                    :tags, :now)
            """), {
                "id": mem_id,
                "agent_id": agent_id,
                "type": memory.get("type", "episodic"),
                "tier": memory.get("tier", "buffer"),
                "content": json.dumps(memory.get("content", {})),
                "importance": memory.get("importance", 0.5),
                "tags": memory.get("tags", []),
                "now": datetime.now(timezone.utc),
            })
            await sess.commit()
        return mem_id

    async def get_memories(self, agent_id: str, tier: str = "working", limit: int = 10) -> list[dict]:
        async with self.session() as sess:
            result = await sess.execute(text("""
                SELECT id, type, tier, content, importance, tags, created_at
                FROM agent_memories
                WHERE agent_id = :agent_id AND tier = :tier
                ORDER BY importance DESC, created_at DESC
                LIMIT :limit
            """), {"agent_id": agent_id, "tier": tier, "limit": limit})
            return [
                {"id": r[0], "type": r[1], "tier": r[2],
                 "content": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                 "importance": r[4], "tags": r[5],
                 "created_at": r[6].isoformat()}
                for r in result.fetchall()
            ]

    async def search_memories_by_vector(
        self, agent_id: str, embedding: list[float], tier: str = "working", limit: int = 10,
    ) -> list[dict]:
        """Search memories by pgvector cosine similarity + importance."""
        async with self.session() as sess:
            result = await sess.execute(text("""
                SELECT id, type, tier, content, importance, tags, created_at,
                       1 - (embedding <=> :embedding::vector) AS similarity
                FROM agent_memories
                WHERE agent_id = :agent_id
                  AND tier = :tier
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding::vector
                LIMIT :limit
            """), {"agent_id": agent_id, "tier": tier, "embedding": embedding, "limit": limit})
            return [
                {"id": r[0], "type": r[1], "tier": r[2],
                 "content": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                 "importance": r[4], "tags": r[5],
                 "created_at": r[6].isoformat(), "similarity": float(r[7])}
                for r in result.fetchall()
            ]

    async def get_all_memories(self, agent_id: str, limit: int = 50) -> list[dict]:
        """Get all memories for an agent across tiers."""
        async with self.session() as sess:
            result = await sess.execute(text("""
                SELECT id, type, tier, content, importance, tags, created_at
                FROM agent_memories
                WHERE agent_id = :agent_id AND tier != 'transient'
                ORDER BY importance DESC, created_at DESC
                LIMIT :limit
            """), {"agent_id": agent_id, "limit": limit})
            return [
                {"id": r[0], "type": r[1], "tier": r[2],
                 "content": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                 "importance": r[4], "tags": r[5],
                 "created_at": r[6].isoformat()}
                for r in result.fetchall()
            ]

    async def update_memory_tier(self, memory_id: str, new_tier: str) -> bool:
        """Promote or archive a memory."""
        async with self.session() as sess:
            result = await sess.execute(text(
                "UPDATE agent_memories SET tier = :tier WHERE id = :id",
            ), {"tier": new_tier, "id": memory_id})
            await sess.commit()
            return result.rowcount > 0

    async def update_memory_embedding(self, memory_id: str, embedding: list[float]) -> None:
        """Update the pgvector embedding for a memory."""
        async with self.session() as sess:
            await sess.execute(text(
                "UPDATE agent_memories SET embedding = :embedding::vector WHERE id = :id",
            ), {"embedding": embedding, "id": memory_id})
            await sess.commit()
