"""
Agent self-reflection (retrospect): analyze past work, extract lessons, and evolve.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def run_retrospect(
    agent_id: str,
    period_days: int = 7,
    db=None,
    agent_service=None,
    reasoning_engine=None,
) -> dict:
    """
    Run a retrospect cycle for an agent.

    Steps:
    1. Load agent profile
    2. Retrieve recent memories (conversations, tasks)
    3. LLM analyzes: what worked, what didn't, what to improve
    4. Extract lessons learned → candidate core memories
    5. Return structured retrospect report
    """
    agent = await agent_service.get_agent(agent_id)
    if not agent:
        return {"error": "agent not found"}

    # Retrieve recent memories
    memories = await db.get_all_memories(agent_id, limit=100)
    recent = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    for m in memories:
        created = m.get("created_at", "")
        if created and created > cutoff.isoformat():
            recent.append(m)

    if not recent:
        return {
            "agent": agent.get("name", agent_id),
            "period_days": period_days,
            "memories_found": 0,
            "summary": "No recent activity to reflect on.",
        }

    # Build memory summary for LLM
    memory_text = "\n".join(
        f"- [{m.get('tier','?')}] {json.dumps(m.get('content',{}), ensure_ascii=False)[:200]}"
        for m in recent[:20]
    )

    agent_name = agent.get("name", "Agent")
    agent_role = agent.get("role", "")

    retrospect_prompt = f"""You are {agent_name}, a {agent_role}. You are doing a weekly retrospect.

## Recent Activity
{memory_text}

## Instructions
Analyze your recent work and produce a structured retrospect report. Reply with ONLY a JSON object:

{{
  "summary": "one paragraph summarizing your week",
  "key_findings": [
    "finding 1: what was learned",
    "finding 2: what could be improved"
  ],
  "proficiency_changes": {{
    "skill_name": "+0.02 (reason)"
  }},
  "candidate_core_memories": [
    "a general lesson that should be remembered permanently"
  ],
  "recommendations": [
    "suggestion for self-improvement"
  ],
  "mood": "positive|neutral|concerned"
}}

Be honest and constructive. If nothing significant happened, say so."""

    try:
        from connector.base import ConversationContext, MemorySnapshot, get_connector

        connector_type = os.getenv("LLM_PROVIDER") or "openai_compatible"
        connector_cls = get_connector(connector_type)
        connector = connector_cls()
        await connector.initialize({
            "provider": os.getenv("LLM_PROVIDER_PRESET", "deepseek"),
            "model": os.getenv("LLM_MODEL", "deepseek-chat"),
            "max_tokens": 800,
            "temperature": 0.3,
        })

        ctx = ConversationContext(
            channel_id="retrospect",
            messages=[{"role": "user", "content": retrospect_prompt}],
            participants=[],
            mentioned=False,
        )
        thought = await connector.think(ctx, MemorySnapshot())
        raw = thought.text.strip()

        # Extract JSON
        if "{" in raw and "}" in raw:
            raw = raw[raw.index("{"):raw.rindex("}")+1]
        report = json.loads(raw)
        report["agent"] = agent_name
        report["period_days"] = period_days
        report["memories_reviewed"] = len(recent)

        logger.info(f"Retrospect complete for {agent_name}: {report.get('mood', '?')}")
        return report

    except Exception as e:
        logger.error(f"Retrospect failed for {agent_name}: {e}")
        return {
            "agent": agent_name,
            "period_days": period_days,
            "memories_found": len(recent),
            "summary": f"Retrospect process encountered an error: {e}",
        }
