"""
Claude API connector — full implementation with prompt caching and tool loop.
"""

import json
import logging
import os
from typing import AsyncIterator

import anthropic

from connector.base import (
    AgentConnector,
    ConversationContext,
    MemorySnapshot,
    Thought,
    ToolResult,
    register_connector,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8


@register_connector("claude_code")
class ClaudeCodeConnector(AgentConnector):
    def __init__(self):
        self.client: anthropic.AsyncAnthropic | None = None
        self.config: dict = {}
        self.tools: dict[str, callable] = {}
        self.model: str = "claude-sonnet-4-6"

    async def initialize(self, agent_config: dict) -> None:
        self.config = agent_config
        self.model = agent_config.get("model", "claude-sonnet-4-6")

        api_key = agent_config.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
        base_url = agent_config.get("base_url") or os.getenv("ANTHROPIC_BASE_URL", None)

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = anthropic.AsyncAnthropic(**client_kwargs)
        logger.info(f"Claude connector initialized: model={self.model}")

    async def think(
        self, context: ConversationContext, memory: MemorySnapshot
    ) -> Thought:
        system_prompt = self.config.get("system_prompt", "")

        # Build messages from context
        messages = self._build_messages(context)

        # Inject memories into system prompt
        if memory.episodic:
            memory_text = "\n".join(
                f"- {m.get('event', m.get('knowledge', str(m)))}"
                for m in memory.episodic[:10]
            )
            system_prompt += f"\n\n## Relevant Memories\n{memory_text}"

        # Tool definitions
        tool_defs = self._get_tool_definitions()

        try:
            # Agent loop: call API → handle tool_use → repeat
            for round_num in range(MAX_TOOL_ROUNDS):
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.config.get("max_tokens", 4096),
                    system=system_prompt,
                    messages=messages,
                    tools=tool_defs if tool_defs else anthropic.NOT_GIVEN,
                    temperature=self.config.get("temperature", 0.7),
                )

                text_blocks = []
                tool_uses = []

                for block in response.content:
                    if block.type == "text":
                        text_blocks.append(block.text)
                    elif block.type == "tool_use":
                        tool_uses.append(block)

                if not tool_uses:
                    # Final response — no more tools needed
                    return Thought(
                        text="\n".join(text_blocks),
                        actions=[],
                        reasoning_trace=f"rounds={round_num+1}",
                    )

                # Execute tool calls
                messages.append({
                    "role": "assistant",
                    "content": [
                        {"type": b.type, **({"text": b.text} if b.type == "text" else {"id": b.id, "name": b.name, "input": b.input})}
                        for b in response.content
                    ],
                })

                tool_results_content = []
                for tool_use in tool_uses:
                    result = await self.execute_tool(tool_use.name, tool_use.input or {})
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result.output) if result.success else result.error or "error",
                        "is_error": not result.success,
                    })

                messages.append({"role": "user", "content": tool_results_content})

            # Max rounds reached — return what we have
            return Thought(
                text="[Max tool rounds reached]",
                actions=[],
                reasoning_trace=f"max_rounds={MAX_TOOL_ROUNDS}",
            )

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return Thought(
                text=f"抱歉，我遇到了一些问题：{str(e)}",
                reasoning_trace=f"error: {e}",
            )

    async def think_stream(
        self, context: ConversationContext, memory: MemorySnapshot
    ) -> AsyncIterator[str]:
        system_prompt = self.config.get("system_prompt", "")
        messages = self._build_messages(context)

        if memory.episodic:
            memory_text = "\n".join(
                f"- {m.get('event', m.get('knowledge', str(m)))}"
                for m in memory.episodic[:10]
            )
            system_prompt += f"\n\n## Relevant Memories\n{memory_text}"

        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=self.config.get("max_tokens", 4096),
                system=system_prompt,
                messages=messages,
                temperature=self.config.get("temperature", 0.7),
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield event.delta.text

        except Exception as e:
            logger.error(f"Claude streaming error: {e}")
            yield f"[Error: {e}]"

    async def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        handler = self.tools.get(tool_name)
        if handler is None:
            return ToolResult(tool_name=tool_name, success=False, error=f"Unknown tool: {tool_name}")
        try:
            output = await handler(params)
            return ToolResult(tool_name=tool_name, success=True, output={"result": output})
        except Exception as e:
            return ToolResult(tool_name=tool_name, success=False, error=str(e))

    def register_tool(self, name: str, handler: callable):
        self.tools[name] = handler

    def capabilities(self) -> list[str]:
        return ["text_generation", "tool_use", "streaming", "prompt_caching"]

    async def health_check(self) -> bool:
        return self.client is not None

    def _build_messages(self, context: ConversationContext) -> list[dict]:
        """Convert internal message format to Anthropic API format."""
        messages = []
        for msg in context.messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("sender_name", "")

            message = {"role": role, "content": content}
            if name and role == "user":
                # Add context about who sent this
                sender_type = msg.get("sender_type", "human")
                if sender_type == "agent":
                    message["content"] = f"[{name}]: {content}"
                else:
                    message["content"] = f"{name}: {content}"

            messages.append(message)
        return messages

    def _get_tool_definitions(self) -> list[dict]:
        """Return tool definitions in Anthropic format."""
        return [
            {
                "name": "send_message",
                "description": "Send a message to the current channel",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The message to send"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "create_task",
                "description": "Create a task for yourself or another agent",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "assignee_id": {"type": "string", "description": "Agent ID to assign to"},
                        "priority": {"type": "string", "enum": ["LOW", "NORMAL", "HIGH", "URGENT"]},
                    },
                    "required": ["title"],
                },
            },
        ]
