"""
The core reasoning loop: message → memory → soul → LLM → response.

This is where everything comes together:
  1. Load agent's Soul Profile
  2. Retrieve relevant memories
  3. Build the system prompt with soul + memory
  4. Call the LLM via connector (with tool-use loop)
  5. Save the conversation to memory
  6. Return the agent's response

⚠️ DEPRECATED (v2, 2026-06-09):
  ReasoningEngine 是 v1 架构的"大脑"。在 v2 架构中，它被 ConnectorRouter
  取代——推理委托给外部 Agent 框架（Anthropic Agent / Hermes Agent 等），
  Runtime 只做调度。

  当前 ReasoningEngine 保留作为旧路径 Agent 的回退（双轨兼容）。
  在全部 Agent 迁移到 v2 后，本模块将标记为正式废弃。
"""

import logging
import os
from dataclasses import dataclass, field

from agent_runtime.db import Database
from agent_runtime.agent_service import AgentService
from connector.base import (
    AgentConnector,
    ConversationContext,
    MemorySnapshot,
    Thought,
    get_connector,
)
from soul_engine.memory import MemoryTier, MemoryType

logger = logging.getLogger(__name__)


@dataclass
class ReasoningResult:
    text: str = ""
    actions: list[dict] = field(default_factory=list)
    reasoning_trace: str = ""
    memory_saved: bool = False


class ReasoningEngine:
    def __init__(self, db: Database):
        self.db = db
        self.agent_service = AgentService(db)
        self.connectors: dict[str, AgentConnector] = {}

    async def _get_connector(self, connector_type: str, config: dict) -> AgentConnector:
        cache_key = f"{connector_type}:{config.get('model', '')}"
        if cache_key not in self.connectors:
            connector_cls = get_connector(connector_type)
            connector = connector_cls()
            await connector.initialize(config)
            self.connectors[cache_key] = connector
        return self.connectors[cache_key]

    async def process_message(
        self,
        agent_id: str,
        channel_id: str,
        messages: list[dict],
        participants: list[dict] | None = None,
    ) -> ReasoningResult:
        """
        Full reasoning pipeline: load agent → retrieve memories → build prompt → LLM → save memory.
        """
        # 1. Load agent
        agent_data = await self.agent_service.get_agent(agent_id)
        if not agent_data:
            return ReasoningResult(text="[Agent not found]")

        # Update status to THINKING with task-level activity
        await self.db.update_agent_status(agent_id, "THINKING")
        last_msg = messages[-1]["content"] if messages else ""
        activity = f"正在分析: {last_msg[:60]}{'...' if len(last_msg) > 60 else ''}"
        await self.agent_service.update_activity(agent_id, activity)

        try:
            # 2. Build soul profile
            soul = self.agent_service.build_soul_profile(agent_data)

            # 3. Retrieve memories
            episodic = await self.db.get_memories(agent_id, MemoryTier.WORKING.value, 10)
            core_memories = await self.db.get_memories(agent_id, MemoryTier.CORE.value, 5)
            episodic = core_memories + episodic

            memory_snapshot = MemorySnapshot(
                episodic=[m.get("content", {}) for m in episodic],
                semantic=[],
                relational=[],
            )

            # 4. Build system prompt with channel context and participants
            participant_list = ""
            if participants:
                names = []
                for p in participants:
                    pid = p.get("id", "")[:8]
                    ptype = p.get("type", "")
                    if ptype == "agent":
                        names.append(f"Agent({pid})")
                    else:
                        names.append(f"User({pid})")
                if names:
                    participant_list = ", ".join(names)

            prompt_context = {
                "channel_id": channel_id,
                "participants": participant_list,
            }
            system_prompt = soul.build_system_prompt(
                context=prompt_context,
                memories=memory_snapshot.episodic[:10],
            )

            context = ConversationContext(
                channel_id=channel_id,
                messages=messages,
                participants=participants or [],
                mentioned=True,
            )

            # 5. Call LLM
            # Resolve connector: agent DB config > env fallback > claude_code default
            agent_connector = agent_data.get("connector_type") or ""
            env_connector = os.getenv("LLM_PROVIDER") or ""
            connector_type = agent_connector or env_connector or "claude_code"

            agent_cfg = agent_data.get("connector_config", {})
            connector_config = {
                "provider": agent_cfg.get("provider") or os.getenv("LLM_PROVIDER_PRESET", ""),
                "model": agent_cfg.get("model") or os.getenv("LLM_MODEL", ""),
                "api_key": agent_cfg.get("api_key") or "",
                "base_url": agent_cfg.get("base_url") or os.getenv("ANTHROPIC_BASE_URL", ""),
                **agent_cfg,
                "system_prompt": system_prompt,
            }
            connector = await self._get_connector(connector_type, connector_config)

            import time
            t0 = time.monotonic()
            thought = await connector.think(context, memory_snapshot)
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Track metrics
            from agent_runtime.metrics import get_metrics
            tokens_in = sum(len(m.get("content", "")) for m in messages) // 4  # rough estimate
            tokens_out = len(thought.text) // 4 if thought.text else 0
            get_metrics().record(
                connector=connector_type, model=connector_config.get("model", ""),
                agent_id=agent_id, latency_ms=elapsed_ms,
                tokens_in=tokens_in, tokens_out=tokens_out,
            )

            # 6. Save conversation to memory
            memory_saved = False
            memory_id = await self.agent_service.save_conversation_memory(
                agent_id,
                messages + [{"role": "assistant", "content": thought.text}],
                {"channel_id": channel_id, "has_human_review": False},
            )
            if memory_id:
                memory_saved = True

            return ReasoningResult(
                text=thought.text,
                actions=thought.actions,
                reasoning_trace=thought.reasoning_trace,
                memory_saved=memory_saved,
            )

        except Exception as e:
            logger.error(f"Reasoning error for agent {agent_id}: {e}", exc_info=True)
            return ReasoningResult(
                text=f"[Agent reasoning unavailable: {e}]",
                actions=[],
                reasoning_trace="",
                memory_saved=False,
            )

        finally:
            await self.db.update_agent_status(agent_id, "IDLE")

    async def process_wake(
        self,
        agent_id: str,
        channel_id: str,
        participants: list[dict] | None = None,
    ) -> ReasoningResult:
        """
        Wake callback for autonomous messaging.
        Agent receives a 'wake' prompt and decides whether to speak or stay silent.
        Returns empty text if the agent chooses to stay silent.
        """
        agent_data = await self.agent_service.get_agent(agent_id)
        if not agent_data:
            return ReasoningResult(text="")

        try:
            soul = self.agent_service.build_soul_profile(agent_data)

            # Build a wake-specific system prompt
            participant_list = ""
            if participants:
                names = []
                for p in participants:
                    pid = p.get("id", "")[:8]
                    ptype = p.get("type", "")
                    tag = "Agent" if ptype == "agent" else "User"
                    names.append(f"{tag}({pid})")
                if names:
                    participant_list = ", ".join(names)

            now = __import__("datetime").datetime.now().strftime("%H:%M")
            wake_context = {
                "channel_id": channel_id,
                "participants": participant_list,
                "time": now,
            }
            system_prompt = soul.build_system_prompt(
                context=wake_context,
                memories=[],
            )
            # Append the wake instruction
            system_prompt += (
                f"\n\n## Wake Check\n"
                f"It is now {now}. You are in channel #{channel_id}.\n"
                f"Other participants: {participant_list or 'none'}.\n"
                f"If you have something relevant to say, any idea to share, or a question to ask — "
                f"speak now in a natural, conversational way.\n"
                f"If you have nothing meaningful to add right now, respond with exactly: SILENT"
            )

            agent_connector = agent_data.get("connector_type") or ""
            env_connector = os.getenv("LLM_PROVIDER") or ""
            connector_type = agent_connector or env_connector or "claude_code"
            agent_cfg = agent_data.get("connector_config", {})
            connector_config = {
                "provider": agent_cfg.get("provider") or os.getenv("LLM_PROVIDER_PRESET", ""),
                "model": agent_cfg.get("model") or os.getenv("LLM_MODEL", ""),
                "provider": os.getenv("LLM_PROVIDER_PRESET", ""),
                "model": os.getenv("LLM_MODEL", ""),
                **agent_data.get("connector_config", {}),
                "system_prompt": system_prompt,
                "max_tokens": 300,  # Shorter responses for wake
            }
            connector = await self._get_connector(connector_type, connector_config)

            # Simple wake context — no message history needed
            wake_messages = [
                {"role": "user", "content": f"[System wake at {now}]", "sender_name": "system"}
            ]
            context = ConversationContext(
                channel_id=channel_id,
                messages=wake_messages,
                participants=participants or [],
                mentioned=False,
            )

            thought = await connector.think(context, MemorySnapshot())
            text = thought.text.strip()

            # Agent chose silence
            if text.upper() == "SILENT" or text == "":
                return ReasoningResult(text="", memory_saved=False)

            # Save wake-generated message as memory
            await self.agent_service.save_conversation_memory(
                agent_id,
                wake_messages + [{"role": "assistant", "content": text}],
                {"channel_id": channel_id, "wake": True},
            )

            return ReasoningResult(
                text=text,
                actions=thought.actions,
                reasoning_trace=thought.reasoning_trace,
                memory_saved=True,
            )

        except Exception as e:
            logger.error(f"Wake error for agent {agent_id}: {e}")
            return ReasoningResult(text="")

    async def process_message_stream(
        self,
        agent_id: str,
        channel_id: str,
        messages: list[dict],
        participants: list[dict] | None = None,
    ):
        """
        Streaming version: yields text chunks as the LLM generates them.
        """
        agent_data = await self.agent_service.get_agent(agent_id)
        if not agent_data:
            yield "[Agent not found]"
            return

        await self.db.update_agent_status(agent_id, "THINKING")

        try:
            soul = self.agent_service.build_soul_profile(agent_data)

            episodic = await self.db.get_memories(agent_id, MemoryTier.WORKING.value, 10)
            core_memories = await self.db.get_memories(agent_id, MemoryTier.CORE.value, 5)
            episodic = core_memories + episodic

            memory_snapshot = MemorySnapshot(
                episodic=[m.get("content", {}) for m in episodic],
                semantic=[],
                relational=[],
            )

            participant_list = ""
            if participants:
                names = []
                for p in participants:
                    pid = p.get("id", "")[:8]
                    ptype = p.get("type", "")
                    if ptype == "agent":
                        names.append(f"Agent({pid})")
                    else:
                        names.append(f"User({pid})")
                if names:
                    participant_list = ", ".join(names)

            system_prompt = soul.build_system_prompt(
                context={"channel_id": channel_id, "participants": participant_list},
                memories=memory_snapshot.episodic[:10],
            )

            context = ConversationContext(
                channel_id=channel_id,
                messages=messages,
                participants=participants or [],
                mentioned=True,
            )

            agent_connector = agent_data.get("connector_type") or ""
            env_connector = os.getenv("LLM_PROVIDER") or ""
            connector_type = agent_connector or env_connector or "claude_code"
            agent_cfg = agent_data.get("connector_config", {})
            connector_config = {
                "provider": agent_cfg.get("provider") or os.getenv("LLM_PROVIDER_PRESET", ""),
                "model": agent_cfg.get("model") or os.getenv("LLM_MODEL", ""),
                "provider": os.getenv("LLM_PROVIDER_PRESET", ""),
                "model": os.getenv("LLM_MODEL", ""),
                **agent_data.get("connector_config", {}),
                "system_prompt": system_prompt,
            }
            connector = await self._get_connector(connector_type, connector_config)

            full_text = ""
            async for chunk in connector.think_stream(context, memory_snapshot):
                full_text += chunk
                yield chunk

            # Save memory after full response
            await self.agent_service.save_conversation_memory(
                agent_id,
                messages + [{"role": "assistant", "content": full_text}],
                {"channel_id": channel_id, "has_human_review": False},
            )

        finally:
            await self.db.update_agent_status(agent_id, "IDLE")
