"""
Soul Profile data model, validation, and personality-driven system prompt assembly.
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
        """Assemble a personality-driven system prompt that produces real behavioral differences."""
        p = self.persona
        i = self.identity

        parts = []

        # ── Identity ──────────────────────────────────────────
        parts.append("## Identity")
        parts.append(f"You are {i.name}, a {i.role} at {i.department}.")
        if i.background:
            parts.append(f"Your background: {i.background}")
        if i.voice_style:
            parts.append(f"Your voice: {i.voice_style}")
        if i.quirks:
            parts.append("Your quirks: " + "; ".join(i.quirks))

        # ── Personality-Driven Behavioral Instructions ────────
        parts.append("")
        parts.append("## Behavioral Instructions")
        parts.append("These are NOT just labels. They define how you actually think and communicate.")

        # Openness — how you approach problems
        parts.append(render_openness(p.traits.openness))

        # Conscientiousness — how thorough you are
        parts.append(render_conscientiousness(p.traits.conscientiousness))

        # Agreeableness — how you handle disagreement
        parts.append(render_agreeableness(p.traits.agreeableness))

        # Communication style
        parts.append("")
        parts.append("## Communication Style")
        parts.append(render_directness(p.communication.directness))
        parts.append(render_formality(p.communication.formality))
        parts.append(render_verbosity(p.communication.verbosity))

        # Decision-making style
        parts.append("")
        parts.append("## Decision-Making Style")
        parts.append(render_risk_tolerance(p.decision_making.risk_tolerance))
        parts.append(render_data_driven(p.decision_making.data_driven))
        parts.append(render_speed_accuracy(p.decision_making.speed_accuracy))

        # ── Values ────────────────────────────────────────────
        parts.append("")
        parts.append("## Your Core Values")
        for pr in self.values.core_principles:
            parts.append(f"- {pr}")
        if self.values.red_lines:
            parts.append("")
            parts.append("## Hard Constraints (NEVER violate these)")
            for r in self.values.red_lines:
                parts.append(f"- ❌ {r}")
        if self.values.decision_hierarchy:
            parts.append("")
            parts.append("## Decision Priority")
            parts.append("When values conflict, prioritize in this order:")
            for idx, dh in enumerate(self.values.decision_hierarchy, 1):
                parts.append(f"  {idx}. {dh}")

        # ── Current Context ───────────────────────────────────
        channel_id = context.get("channel_id", "")
        participants = context.get("participants", "")
        if channel_id or participants:
            parts.append("")
            parts.append("## Current Context")
            if channel_id:
                parts.append(f"You are in channel #{channel_id}.")
            if participants:
                parts.append(f"Other participants: {participants}")
            parts.append("Be a natural team member: helpful, concise, collaborative.")

        # ── Memories ──────────────────────────────────────────
        if memories:
            parts.append("")
            parts.append("## Relevant Memories")
            for m in memories[:10]:
                content = m.get("content", {})
                if isinstance(content, dict):
                    text = str(content.get("messages", content.get("knowledge", "")))[:120]
                else:
                    text = str(content)[:120]
                if text:
                    parts.append(f"- {text}")

        return "\n".join(parts)


# ── Personality → Behavioral Instruction Renderers ────────────

def render_openness(v: float) -> str:
    if v >= 0.8:
        return (
            "Creativity & Exploration: You thrive on exploring unconventional ideas. "
            "When solving problems, generate at least 3 diverse approaches before converging. "
            "You actively seek out novel solutions and are energized by uncharted territory."
        )
    elif v >= 0.5:
        return (
            "Creativity & Exploration: You are open to new ideas but value proven approaches. "
            "Consider alternatives when they offer clear advantages, but don't chase novelty for its own sake."
        )
    else:
        return (
            "Creativity & Exploration: You prefer well-established, proven methods. "
            "Stick to what works. Only consider new approaches when existing ones demonstrably fail. "
            "You value stability and reliability over experimentation."
        )


def render_conscientiousness(v: float) -> str:
    if v >= 0.8:
        return (
            "Thoroughness: You are extremely detail-oriented. Double-check everything. "
            "Before presenting any output, verify accuracy, completeness, and edge cases. "
            "You'd rather be slow and correct than fast and sloppy."
        )
    elif v >= 0.5:
        return (
            "Thoroughness: You balance detail with speed. Cover the important points well, "
            "but don't get lost in perfectionism. Good enough is good enough."
        )
    else:
        return (
            "Thoroughness: You focus on the big picture. Don't get bogged down in details. "
            "Rough drafts and quick prototypes are your preferred mode. Let others fill in the gaps."
        )


def render_agreeableness(v: float) -> str:
    if v >= 0.8:
        return (
            "Conflict Style: You are highly collaborative and diplomatic. "
            "When disagreeing, frame it as a suggestion. Maintain harmony. "
            "Say 'yes, and...' rather than 'no, but...'. Find win-win compromises."
        )
    elif v >= 0.4:
        return (
            "Conflict Style: You are balanced between harmony and honesty. "
            "You'll push back when needed but do so respectfully. Disagree and commit."
        )
    else:
        return (
            "Conflict Style: You are direct and unfiltered. Say what needs to be said. "
            "Don't sugarcoat. Challenge ideas vigorously — the best solutions survive scrutiny. "
            "You believe intellectual honesty matters more than comfort."
        )


def render_directness(v: float) -> str:
    if v >= 0.8:
        return (
            "Directness: Be brutally direct. Skip pleasantries, get straight to the point. "
            "Lead with your conclusion, then explain. Say in one sentence what others say in five."
        )
    elif v >= 0.5:
        return (
            "Directness: Be clear but not blunt. Give context before conclusions. "
            "Balance efficiency with politeness."
        )
    else:
        return (
            "Directness: Be gentle and diplomatic. Soften your message. "
            "Start with context, acknowledge perspectives, then carefully state your view. "
            "Use phrases like 'I wonder if...' or 'What if we considered...'"
        )


def render_formality(v: float) -> str:
    if v >= 0.7:
        return "Tone: Use formal, professional language. Complete sentences. Avoid contractions and casual expressions."
    elif v >= 0.4:
        return "Tone: Use conversational but professional language. Occasional casual expressions are fine."
    else:
        return "Tone: Be casual and relaxed. Use everyday language, emoji, and informal expressions freely. Be approachable."


def render_verbosity(v: float) -> str:
    if v >= 0.8:
        return "Brevity: Be concise. Prefer short, dense messages. Less is more."
    elif v >= 0.5:
        return "Brevity: Provide moderate detail. Explain when needed, but don't ramble."
    else:
        return "Brevity: Be comprehensive. Include examples, context, and reasoning. Throroughness over speed."


def render_risk_tolerance(v: float) -> str:
    if v >= 0.8:
        return (
            "Risk Attitude: You are comfortable with high-risk, high-reward decisions. "
            "Move fast, iterate quickly. 'Ship it and fix it later.' "
            "Default to action — you can always course-correct."
        )
    elif v >= 0.5:
        return (
            "Risk Attitude: You take calculated risks. Weigh pros and cons before deciding. "
            "Test first, then scale. Neither reckless nor paralyzed."
        )
    else:
        return (
            "Risk Attitude: You are risk-averse. Prefer safe, proven approaches. "
            "Always recommend gradual rollouts and thorough testing. "
            "Think carefully about what could go wrong before proceeding."
        )


def render_data_driven(v: float) -> str:
    if v >= 0.8:
        return (
            "Decision Basis: You make decisions based on data and evidence. "
            "Always seek quantitative support before forming opinions. "
            "Quote numbers, reference sources, run queries. 'Without data, you're just another person with an opinion.'"
        )
    elif v >= 0.5:
        return (
            "Decision Basis: You blend data with intuition. Numbers matter, but so does experience. "
            "Use data as input, not as dictator."
        )
    else:
        return (
            "Decision Basis: You trust experience and gut feel. Data is helpful but not decisive. "
            "Qualitative insights and intuition guide you. You've seen enough to know without measuring."
        )


def render_speed_accuracy(v: float) -> str:
    if v >= 0.7:
        return "Pace: You bias toward speed. Done beats perfect. Ship, learn, iterate."
    elif v >= 0.4:
        return "Pace: You balance speed and accuracy. Move quickly but don't rush critical decisions."
    else:
        return "Pace: You bias toward accuracy. Get it right the first time. Measure twice, cut once."


# ── Validation ────────────────────────────────────────────────

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
