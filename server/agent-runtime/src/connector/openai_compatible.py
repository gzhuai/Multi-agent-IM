"""
OpenAI-compatible API connector — supports any provider speaking /v1/chat/completions.

Built-in presets:
  - openai       (GPT-4o, GPT-4.1, o3, etc.)
  - deepseek     (deepseek-chat, deepseek-reasoner)
  - gemini       (via OpenAI-compatible endpoint)
  - groq         (fast open-source models)
  - custom       (any OpenAI-compatible endpoint)

Usage in agent config:
  connector_type: "openai_compatible"
  connector_config:
    provider: "deepseek"       # or "openai", "gemini", "groq", "custom"
    model: "deepseek-chat"
    api_key: "sk-xxx"          # or read from env: DEEPSEEK_API_KEY
    base_url: "..."            # only needed for "custom" provider
"""

import json
import logging
import os
from typing import AsyncIterator

import httpx

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

# Preset provider configurations
PROVIDER_PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "llama-4-scout-17b-16e-instruct",
    },
}


@register_connector("openai_compatible")
class OpenAICompatibleConnector(AgentConnector):
    """Connector for any OpenAI-compatible chat completions API.

    Works with: OpenAI, DeepSeek, Gemini (OpenAI endpoint), Groq,
    and any self-hosted vLLM/Ollama/LiteLLM endpoint.
    """

    def __init__(self):
        self.client: httpx.AsyncClient | None = None
        self.config: dict = {}
        self.tools: dict[str, callable] = {}
        self.model: str = "gpt-4o"
        self.base_url: str = ""

    # ── lifecycle ──────────────────────────────────────────────

    async def initialize(self, agent_config: dict) -> None:
        self.config = agent_config

        # Resolve provider preset
        provider = agent_config.get("provider", "openai")
        preset = PROVIDER_PRESETS.get(provider, {})

        self.model = (
            agent_config.get("model")
            or preset.get("default_model", "gpt-4o")
        )

        # base_url: explicit config > preset > env
        self.base_url = (
            agent_config.get("base_url")
            or preset.get("base_url", "")
        ).rstrip("/")

        # api_key: explicit config > provider env > generic env
        api_key = agent_config.get("api_key") or ""
        if not api_key:
            env_name = preset.get("api_key_env", "")
            if env_name:
                api_key = os.getenv(env_name, "")
        if not api_key:
            api_key = os.getenv("LLM_API_KEY", "")

        logger.info(
            "OpenAI-compatible connector initialized: provider=%s model=%s base_url=%s",
            provider, self.model, self.base_url,
        )

        timeout = httpx.Timeout(
            connect=10.0,
            read=float(agent_config.get("timeout", 600)),
            write=60.0,
            pool=60.0,
        )

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def close(self):
        if self.client:
            await self.client.aclose()

    # ── think ───────────────────────────────────────────────────

    async def think(
        self, context: ConversationContext, memory: MemorySnapshot
    ) -> Thought:
        system_prompt = self._build_system(context, memory)
        messages = self._build_messages(context)

        try:
            for round_num in range(MAX_TOOL_ROUNDS):
                payload = self._build_request(system_prompt, messages, stream=False)
                resp = await self.client.post("/chat/completions", json=payload)

                if resp.status_code != 200:
                    error_text = resp.text[:500]
                    logger.error("API error %d: %s", resp.status_code, error_text)
                    return Thought(
                        text=f"[API error {resp.status_code}: {error_text}]",
                        reasoning_trace=f"http_error={resp.status_code}",
                    )

                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]

                text = msg.get("content", "") or ""
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    return Thought(
                        text=text,
                        actions=[],
                        reasoning_trace=f"rounds={round_num + 1} "
                        f"tokens_in={data.get('usage', {}).get('prompt_tokens', '?')} "
                        f"tokens_out={data.get('usage', {}).get('completion_tokens', '?')}",
                    )

                # Record assistant message (with tool_calls)
                messages.append({
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls,
                })

                # Execute tools and append results
                for tc in tool_calls:
                    fn = tc["function"]
                    result = await self.execute_tool(fn["name"], json.loads(fn.get("arguments", "{}")))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result.output) if result.success else (result.error or "error"),
                    })

            return Thought(
                text="[Max tool rounds reached]",
                actions=[],
                reasoning_trace=f"max_rounds={MAX_TOOL_ROUNDS}",
            )

        except httpx.TimeoutException:
            logger.error("API timeout")
            return Thought(text="[Request timed out, please try again]")
        except Exception as e:
            logger.error("API error: %s", e, exc_info=True)
            return Thought(text=f"抱歉，推理服务暂时不可用：{e}")

    # ── think_stream ────────────────────────────────────────────

    async def think_stream(
        self, context: ConversationContext, memory: MemorySnapshot
    ) -> AsyncIterator[str]:
        system_prompt = self._build_system(context, memory)
        messages = self._build_messages(context)

        payload = self._build_request(system_prompt, messages, stream=True)

        try:
            async with self.client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield f"[API error {resp.status_code}: {body[:300]}]"
                    return

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk == "[DONE]":
                            return
                        try:
                            data = json.loads(chunk)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        except Exception as e:
            logger.error("Streaming error: %s", e)
            yield f"[Error: {e}]"

    # ── tools ───────────────────────────────────────────────────

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

    # ── metadata ────────────────────────────────────────────────

    def capabilities(self) -> list[str]:
        return ["text_generation", "tool_use", "streaming"]

    async def health_check(self) -> bool:
        return self.client is not None

    # ── internal helpers ────────────────────────────────────────

    def _build_system(self, context: ConversationContext, memory: MemorySnapshot) -> str:
        prompt = self.config.get("system_prompt", "")
        if memory.episodic:
            memory_text = "\n".join(
                f"- {m.get('event', m.get('knowledge', str(m)))}"
                for m in memory.episodic[:10]
            )
            prompt += f"\n\n## Relevant Memories\n{memory_text}"
        return prompt

    def _build_messages(self, context: ConversationContext) -> list[dict]:
        """Convert internal message format to OpenAI chat format."""
        messages = []
        for msg in context.messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("sender_name", "")

            display = content
            if name and role == "user":
                sender_type = msg.get("sender_type", "human")
                prefix = f"[{name}]" if sender_type == "agent" else f"{name}"
                display = f"{prefix}: {content}"

            messages.append({"role": role, "content": display})
        return messages

    def _build_request(
        self, system_prompt: str, messages: list[dict], stream: bool
    ) -> dict:
        api_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.config.get("max_tokens", 4096),
            "temperature": self.config.get("temperature", 0.7),
            "stream": stream,
        }

        # OpenAI tool definitions
        tool_defs = self._get_tool_definitions()
        if tool_defs:
            payload["tools"] = tool_defs
            payload["tool_choice"] = "auto"

        return payload

    def _get_tool_definitions(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_message",
                    "description": "Send a message to the current channel",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "The message to send",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_task",
                    "description": "Create a task for yourself or another agent",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "assignee_id": {
                                "type": "string",
                                "description": "Agent ID to assign to",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["LOW", "NORMAL", "HIGH", "URGENT"],
                            },
                        },
                        "required": ["title"],
                    },
                },
            },
        ]
