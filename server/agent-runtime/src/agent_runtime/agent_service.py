"""
Agent lifecycle management and coordination.
"""

import logging
from typing import Optional

from agent_runtime.db import Database
from soul_engine.profile import SoulProfile, Identity, Persona, PersonaTraits, CommunicationStyle, DecisionStyle, ValueSystem
from soul_engine.memory import Memory, MemoryTier, MemoryType, MemoryBudget

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self, db: Database):
        self.db = db

    async def create_agent(self, data: dict) -> dict:
        agent = await self.db.create_agent(data)
        logger.info(f"Agent created: {agent['name']} ({agent['id']})")
        return agent

    async def get_agent(self, agent_id: str) -> Optional[dict]:
        return await self.db.get_agent(agent_id)

    async def list_agents(self, org_id: str = "default") -> list[dict]:
        return await self.db.list_agents(org_id)

    async def activate_agent(self, agent_id: str) -> str:
        agent = await self.db.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")
        await self.db.update_agent_status(agent_id, "IDLE")
        logger.info(f"Agent activated: {agent['name']}")
        return "IDLE"

    async def pause_agent(self, agent_id: str) -> str:
        await self.db.update_agent_status(agent_id, "PAUSED")
        return "PAUSED"

    async def resume_agent(self, agent_id: str) -> str:
        await self.db.update_agent_status(agent_id, "IDLE")
        return "IDLE"

    def build_soul_profile(self, agent_data: dict) -> SoulProfile:
        identity_data = agent_data.get("identity", {})
        persona_data = agent_data.get("persona", {})
        values_data = agent_data.get("value_system", {})

        comm = persona_data.get("communication", {})
        decision = persona_data.get("decision_making", {})

        identity = Identity(
            name=agent_data.get("name", identity_data.get("name", "")),
            display_name=agent_data.get("display_name", identity_data.get("display_name", "")),
            role=agent_data.get("role", identity_data.get("role", "")),
            department=agent_data.get("department", identity_data.get("department", "")),
            level=agent_data.get("level", identity_data.get("level", 1)),
            background=identity_data.get("background", ""),
            voice_style=identity_data.get("voice_style", ""),
            quirks=identity_data.get("quirks", []),
        )

        persona = Persona(
            traits=PersonaTraits(
                openness=persona_data.get("openness", 0.5),
                conscientiousness=persona_data.get("conscientiousness", 0.5),
                extraversion=persona_data.get("extraversion", 0.5),
                agreeableness=persona_data.get("agreeableness", 0.5),
                neuroticism=persona_data.get("neuroticism", 0.5),
            ),
            communication=CommunicationStyle(
                verbosity=comm.get("verbosity", 0.5),
                formality=comm.get("formality", 0.5),
                humor=comm.get("humor", 0.3),
                directness=comm.get("directness", 0.5),
            ),
            decision_making=DecisionStyle(
                risk_tolerance=decision.get("risk_tolerance", 0.5),
                data_driven=decision.get("data_driven", 0.5),
                speed_accuracy=decision.get("speed_accuracy", 0.5),
                autonomy=decision.get("autonomy", 0.5),
            ),
        )

        values = ValueSystem(
            core_principles=values_data.get("core_principles", []),
            red_lines=values_data.get("red_lines", []),
            decision_hierarchy=values_data.get("decision_hierarchy", []),
        )

        return SoulProfile(identity=identity, persona=persona, values=values)

    async def save_conversation_memory(self, agent_id: str, messages: list[dict], context: dict) -> Optional[str]:
        """Save a conversation to agent memory if it passes the importance threshold."""
        from soul_engine.memory import assess_importance
        score = assess_importance(messages, context)

        if score < 0.3:
            return None  # Transient, don't store

        tier = MemoryTier.CORE.value if score >= 0.8 else MemoryTier.WORKING.value if score >= 0.5 else MemoryTier.BUFFER.value

        memory = {
            "type": MemoryType.EPISODIC.value,
            "tier": tier,
            "content": {"messages": messages, "context": context},
            "importance": score,
            "tags": context.get("tags", []),
        }

        mem_id = await self.db.save_memory(agent_id, memory)
        logger.debug(f"Memory saved: {mem_id} (tier={tier}, score={score:.2f})")
        return mem_id

    async def inject_knowledge_document(self, agent_id: str, filename: str, content: str) -> str:
        """Inject an MD document into the agent's semantic memory."""
        memory = {
            "type": MemoryType.SEMANTIC.value,
            "tier": MemoryTier.WORKING.value,
            "content": {
                "knowledge": content,
                "source": filename,
                "confidence": 0.95,  # High confidence for human-provided docs
            },
            "importance": 0.75,
            "tags": ["knowledge_document", filename.replace(".md", "")],
        }
        mem_id = await self.db.save_memory(agent_id, memory)
        logger.info(f"Knowledge document '{filename}' injected for agent {agent_id}")
        return mem_id

    async def update_activity(self, agent_id: str, activity: str, task_count: int | None = None) -> None:
        """Broadcast task-level activity status for an agent."""
        # Update in Redis for real-time broadcast (Phase 1: log + DB flag)
        logger.info(f"Agent {agent_id} activity: {activity}")
        if task_count is not None:
            logger.info(f"Agent {agent_id} task_count: {task_count}")

    # In-memory task queues (per agent) — Phase 2 moves to Redis
    _task_queues: dict[str, list[dict]] = {}

    async def enqueue_task(self, agent_id: str, task: dict, priority: str = "NORMAL") -> dict:
        """Enqueue a task with priority-based preemptive scheduling."""
        if agent_id not in self._task_queues:
            self._task_queues[agent_id] = []

        priority_order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
        task["priority"] = priority
        task["priority_rank"] = priority_order.get(priority, 2)
        task["enqueued_at"] = __import__("datetime").datetime.now().isoformat()

        # Insert at correct position (preemptive: higher priority goes first)
        insert_at = 0
        for i, t in enumerate(self._task_queues[agent_id]):
            if task["priority_rank"] >= t.get("priority_rank", 2):
                insert_at = i + 1
            else:
                break

        self._task_queues[agent_id].insert(insert_at, task)
        logger.info(f"Task enqueued for {agent_id}: {task.get('title')} [{priority}] pos={insert_at}")

        # Update activity based on new task
        await self.update_activity(
            agent_id,
            f"📋 {task.get('title', '新任务')}",
            len(self._task_queues[agent_id]),
        )

        return {"queued": True, "position": insert_at, "total_queued": len(self._task_queues[agent_id])}

    async def dequeue_task(self, agent_id: str) -> dict | None:
        """Get the next highest-priority task for an agent."""
        queue = self._task_queues.get(agent_id, [])
        if not queue:
            return None

        task = queue.pop(0)
        logger.info(f"Task dequeued for {agent_id}: {task.get('title')}")

        # Update activity to next task or idle
        if queue:
            next_task = queue[0]
            await self.update_activity(
                agent_id,
                f"📋 {next_task.get('title', '下一个任务')}",
                len(queue),
            )
        else:
            await self.update_activity(agent_id, "空闲", 0)

        return task
