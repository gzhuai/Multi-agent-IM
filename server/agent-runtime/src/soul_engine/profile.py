"""
Soul Profile data model, validation, and system prompt assembly.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PersonaTraits:
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5

    def __post_init__(self):
        for name in ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]:
            val = getattr(self, name)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {val}")


@dataclass
class CommunicationStyle:
    verbosity: float = 0.5
    formality: float = 0.5
    humor: float = 0.3
    directness: float = 0.5


@dataclass
class DecisionStyle:
    risk_tolerance: float = 0.5
    data_driven: float = 0.5
    speed_accuracy: float = 0.5
    autonomy: float = 0.5


@dataclass
class Persona:
    traits: PersonaTraits = field(default_factory=PersonaTraits)
    communication: CommunicationStyle = field(default_factory=CommunicationStyle)
    decision_making: DecisionStyle = field(default_factory=DecisionStyle)


@dataclass
class ValueSystem:
    core_principles: list[str] = field(default_factory=list)
    red_lines: list[str] = field(default_factory=list)
    decision_hierarchy: list[str] = field(default_factory=list)


@dataclass
class Identity:
    name: str = ""
    display_name: str = ""
    role: str = ""
    department: str = ""
    level: int = 1
    background: str = ""
    voice_style: str = ""
    quirks: list[str] = field(default_factory=list)


@dataclass
class SoulProfile:
    identity: Identity = field(default_factory=Identity)
    persona: Persona = field(default_factory=Persona)
    values: ValueSystem = field(default_factory=ValueSystem)

    def build_system_prompt(self, context: dict, memories: list[dict]) -> str:
        """Assemble the full system prompt from soul profile + context + memories."""
        parts = [
            f"## Identity\nYou are {self.identity.name}, {self.identity.role} at {self.identity.department}.",
            f"Background: {self.identity.background}",
            f"Communication style: {self.identity.voice_style}",
            "",
            f"## Personality",
            f"Openness: {self.persona.traits.openness:.0%} | "
            f"Conscientiousness: {self.persona.traits.conscientiousness:.0%} | "
            f"Directness: {self.persona.communication.directness:.0%}",
            f"Risk tolerance: {self.persona.decision_making.risk_tolerance:.0%} | "
            f"Data-driven: {self.persona.decision_making.data_driven:.0%}",
            "",
            "## Values",
        ]
        for p in self.values.core_principles:
            parts.append(f"- {p}")
        if self.values.red_lines:
            parts.append("\n## Hard Constraints (DO NOT VIOLATE)")
            for r in self.values.red_lines:
                parts.append(f"- {r}")

        if memories:
            parts.append("\n## Relevant Memories")
            for m in memories[:10]:
                parts.append(f"- {m.get('event', m.get('knowledge', ''))}")

        return "\n".join(parts)


def validate_agent_profile(profile: dict, mode: str = "production") -> None:
    """Validate an agent profile dict. In production mode, red_lines must not be empty."""
    required = ["name", "role"]
    for key in required:
        if key not in profile:
            raise ValueError(f"Agent profile missing required field: {key}")

    if mode == "production":
        red_lines = profile.get("values", {}).get("red_lines", [])
        if not red_lines:
            raise ValueError("Production agent must have at least one red_line")


def check_red_lines(red_lines: list[str], action: dict) -> list[str]:
    """Check if an action violates any red lines. Returns list of violated rules."""
    violations = []
    action_type = action.get("type", "")
    target = action.get("target", "")
    url = action.get("url", "")
    approved = action.get("approved", False)

    for rule in red_lines:
        if "生产数据库" in rule and target == "production" and "write" in action_type:
            violations.append(rule)
        elif "修改生产数据库" in rule and target == "production" and "delete" in action_type:
            violations.append(rule)
        elif "外部" in rule and "http" in action_type and not url.startswith("internal"):
            violations.append(rule)
        elif "删除" in rule and "delete" in action_type and not approved:
            violations.append(rule)

    return violations
