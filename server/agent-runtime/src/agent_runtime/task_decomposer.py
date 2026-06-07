"""
LLM-powered task decomposition.

When an agent receives a complex task, it analyzes the task with its reasoning engine
and breaks it down into 2-5 concrete subtasks, each assigned to the most suitable agent.
"""

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SubTask:
    title: str
    description: str
    suggested_assignee: str = ""  # agent name or ID hint
    priority: str = "NORMAL"


@dataclass
class DecomposeResult:
    subtasks: list[SubTask] = field(default_factory=list)
    reasoning: str = ""


async def decompose_task(
    agent_id: str,
    task_title: str,
    task_description: str,
    available_agents: list[dict],
    reasoning_engine,  # ReasoningEngine instance
) -> DecomposeResult:
    """
    Use the agent's LLM to decompose a complex task into subtasks.

    The LLM receives the task description and available agents, then outputs
    a structured JSON list of subtasks.
    """
    agent_names = "\n".join(
        f"- {a.get('name', a.get('id', 'unknown'))} ({a.get('role', '')})"
        for a in available_agents
    )

    decompose_prompt = f"""You are a project manager AI. Your job is to break down a complex task into concrete subtasks.

## Task to decompose
**Title**: {task_title}
**Description**: {task_description}

## Available agents
{agent_names if agent_names else "No other agents available — assign subtasks to yourself if needed."}

## Instructions
1. Analyze the task and break it into 2-5 concrete, actionable subtasks
2. Each subtask should be small enough for one agent to complete
3. Assign each subtask to the most suitable available agent (or yourself)
4. Return ONLY a JSON array of objects with these fields:
   - "title": short title
   - "description": what needs to be done
   - "assignee_hint": agent name or "self"
   - "priority": "HIGH"/"NORMAL"/"LOW"

Output ONLY the JSON array, nothing else."""

    # Use the agent's reasoning engine to call the LLM
    try:
        from connector.base import ConversationContext, MemorySnapshot
        from connector.base import get_connector

        # Resolve connector from env
        connector_type = os.getenv("LLM_PROVIDER") or "openai_compatible"
        connector_cls = get_connector(connector_type)
        connector = connector_cls()
        await connector.initialize({
            "provider": os.getenv("LLM_PROVIDER_PRESET", "deepseek"),
            "model": os.getenv("LLM_MODEL", "deepseek-chat"),
            "max_tokens": 1000,
            "temperature": 0.3,
        })

        ctx = ConversationContext(
            channel_id="task-decomposer",
            messages=[{"role": "user", "content": decompose_prompt}],
            participants=[],
            mentioned=False,
        )
        thought = await connector.think(ctx, MemorySnapshot())
        raw = thought.text.strip()

        # Extract JSON from response (handle markdown code fences)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        subtasks = []
        for item in data:
            subtasks.append(SubTask(
                title=item.get("title", ""),
                description=item.get("description", ""),
                suggested_assignee=item.get("assignee_hint", ""),
                priority=item.get("priority", "NORMAL"),
            ))

        logger.info(
            "Task decomposed: '%s' → %d subtasks",
            task_title, len(subtasks),
        )
        return DecomposeResult(subtasks=subtasks, reasoning=thought.reasoning_trace)

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse decomposition JSON: %s", e)
        # Fallback: create a single subtask
        return DecomposeResult(
            subtasks=[SubTask(
                title=f"完成: {task_title}",
                description=task_description,
                suggested_assignee="self",
                priority="NORMAL",
            )],
            reasoning="JSON parse fallback",
        )
    except Exception as e:
        logger.error("Task decomposition failed: %s", e)
        return DecomposeResult(
            subtasks=[SubTask(
                title=task_title,
                description=task_description,
                suggested_assignee="self",
                priority="NORMAL",
            )],
            reasoning=f"decomposition error: {e}",
        )
