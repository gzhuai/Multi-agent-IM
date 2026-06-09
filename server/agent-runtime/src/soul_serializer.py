"""
SoulSerializer — SoulProfile 到各框架的格式转换。

职责:
  1. 从 agent_data（DB 中的 dict）构建 SoulProfile
  2. 将 SoulProfile 序列化为各框架所需的 System Prompt / Agent Profile 格式
  3. 支持 Anthropic、Hermes、通用 OpenAI-compatible 三种输出格式

与第一代的区别:
  v1: ReasoningEngine 内部自己拼接 system prompt，逻辑分散
  v2: SoulSerializer 是独立服务，各 Connector 调用它获取格式化的灵魂文本
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soul_engine.profile import (
    SoulProfile,
    Identity,
    Persona,
    PersonaTraits,
    CommunicationStyle,
    DecisionStyle,
    ValueSystem,
)


@dataclass
class SerializedSoul:
    """序列化后的灵魂数据 — 供各 Connector 使用。"""

    # 原始 struct（Python 对象）
    soul_profile: SoulProfile

    # 各框架格式
    anthropic_system: str = ""      # Anthropic API 的 system 参数
    openai_system: str = ""         # OpenAI-compatible API 的 system message content
    hermes_profile: dict[str, Any] = (
        None
    )  # Hermes Agent 的 agent profile dict

    # 元数据
    rendered_at: str = ""
    framework_hints: dict[str, Any] = None  # 框架特定的额外提示


class SoulSerializer:
    """
    SoulProfile → 框架格式 的转换器。

    使用方式:
      serializer = SoulSerializer()
      soul = serializer.build_from_db(agent_data)
      serialized = serializer.serialize(soul)
      # 在 Anthropic Connector 中使用:
      system_prompt = serialized.anthropic_system
    """

    # ── 构建 ──────────────────────────────────────────────────────

    def build_from_db(self, agent_data: dict[str, Any]) -> SoulProfile:
        """从 agent_data dict 构建 SoulProfile。

        agent_data 来自 PostgreSQL agents 表（含 identity/persona/value_system JSONB）。
        """
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

    # ── 序列化 ────────────────────────────────────────────────────

    def serialize(
        self,
        soul: SoulProfile,
        context: dict[str, Any] | None = None,
        memories: list[dict[str, Any]] | None = None,
        runtime_hints: dict[str, Any] | None = None,
    ) -> SerializedSoul:
        """将 SoulProfile 序列化为所有框架格式。

        Args:
            soul: 灵魂画像
            context: 当前上下文 {channel_id, participants, ...}
            memories: 相关记忆列表
            runtime_hints: Runtime 附加提示（如 agent 的 tool_permissions）
        """
        ctx = context or {}
        mems = memories or []
        import datetime
        return SerializedSoul(
            soul_profile=soul,
            anthropic_system=self._to_anthropic(soul, ctx, mems, runtime_hints),
            openai_system=self._to_openai(soul, ctx, mems, runtime_hints),
            hermes_profile=self._to_hermes(soul, ctx, mems, runtime_hints),
            rendered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            framework_hints=runtime_hints,
        )

    # ── Anthropic 格式 ────────────────────────────────────────────

    def _to_anthropic(
        self,
        soul: SoulProfile,
        context: dict[str, Any],
        memories: list[dict[str, Any]],
        hints: dict[str, Any] | None,
    ) -> str:
        """
        生成 Anthropic API 的 system 参数。

        Anthropic 的 system 参数是一个纯文本字符串（或带 cache_control 的 content block）。
        这里只生成文本内容；cache_control 标记由 AnthropicAgentConnector 自己添加。
        """
        parts = soul.build_system_prompt(context, memories)

        # ── 操作约束 (给 Agent 的行动指令，不仅是说话指令) ──
        parts += "\n\n## Action Capabilities"
        parts += "\nYou are NOT just a conversational assistant. You have REAL tools to interact with the world:"
        parts += "\n- You CAN read, write, and modify files in the workspace."
        parts += "\n- You CAN execute shell commands and see their output."
        parts += "\n- You CAN search codebases and analyze results."
        parts += "\n- You CAN send messages to the IM channel you're in."
        parts += "\n- You CAN create and update tasks."
        parts += "\n\nWhen someone asks you to DO something, USE YOUR TOOLS. Don't just describe what you would do — actually do it."

        # ── 审批提示 ──
        if hints and hints.get("approval_required_tools"):
            tool_names = ", ".join(hints["approval_required_tools"])
            parts += (
                f"\n\n## Important"
                f"\nSome operations ({tool_names}) require human approval before execution."
                f"\nWhen you need to perform such an operation, clearly explain why and wait for approval."
            )

        return parts

    # ── OpenAI-compatible 格式 ────────────────────────────────────

    def _to_openai(
        self,
        soul: SoulProfile,
        context: dict[str, Any],
        memories: list[dict[str, Any]],
        hints: dict[str, Any] | None,
    ) -> str:
        """生成 OpenAI-compatible API 的 system message content。

        与 Anthropic 格式基本相同，但不包含 cache_control 标记。
        """
        # 复用 Anthropic 格式（去除 cache 相关的内容）
        anthropic_text = self._to_anthropic(soul, context, memories, hints)
        # 移除 "cache_control" 提示（如果有）
        return anthropic_text

    # ── Hermes 格式 ───────────────────────────────────────────────

    def _to_hermes(
        self,
        soul: SoulProfile,
        context: dict[str, Any],
        memories: list[dict[str, Any]],
        hints: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """生成 Hermes Agent (NousResearch) 的 agent profile dict。

        Hermes Agent 通过 AIAgent 构造函数接收配置。
        我们提供的是 profile 元数据，由 HermesConnector 组装到 AIAgent 参数中。
        """
        p = soul.persona
        i = soul.identity

        return {
            "identity": {
                "name": i.name,
                "display_name": i.display_name,
                "role": i.role,
                "department": i.department,
                "background": i.background,
                "voice_style": i.voice_style,
                "quirks": i.quirks,
            },
            "persona": {
                "traits": {
                    "openness": p.traits.openness,
                    "conscientiousness": p.traits.conscientiousness,
                    "extraversion": p.traits.extraversion,
                    "agreeableness": p.traits.agreeableness,
                    "neuroticism": p.traits.neuroticism,
                },
                "communication": {
                    "verbosity": p.communication.verbosity,
                    "formality": p.communication.formality,
                    "humor": p.communication.humor,
                    "directness": p.communication.directness,
                },
                "decision_making": {
                    "risk_tolerance": p.decision_making.risk_tolerance,
                    "data_driven": p.decision_making.data_driven,
                    "speed_accuracy": p.decision_making.speed_accuracy,
                    "autonomy": p.decision_making.autonomy,
                },
            },
            "values": {
                "core_principles": soul.values.core_principles,
                "red_lines": soul.values.red_lines,
                "decision_hierarchy": soul.values.decision_hierarchy,
            },
            "context": context,
            "memories": [
                _serialize_memory(m) for m in (memories or [])[:20]
            ],
            "runtime_hints": hints or {},
        }


def _serialize_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """将 memory dict 转换为简短的可注入格式。"""
    content = memory.get("content", {})
    if isinstance(content, dict):
        text = (
            content.get("knowledge", "")
            or str(content.get("messages", ""))
            or str(content)
        )[:200]
    else:
        text = str(content)[:200]
    return {
        "tier": memory.get("tier", "buffer"),
        "type": memory.get("type", "episodic"),
        "importance": memory.get("importance", 0.5),
        "summary": text,
    }
