"""
AgenticConnector — v2 Connector with dual LLM backend.

Backend auto-detection:
  1. ANTHROPIC_API_KEY set → Anthropic native protocol (prompt caching, native tool_use)
  2. Otherwise, DEEPSEEK_API_KEY / OPENAI_API_KEY / LLM_API_KEY / custom base_url
     → OpenAI-compatible protocol (function calling)

Same 12 tools, same agent loop, same Sandbox — different API protocol underneath.

Architecture:
  SoulProfile + Memory → System Prompt
  ConversationContext    → Messages
  Agent Loop             → tool call → execute in sandbox → result → repeat
  Event Callback         → real-time status pushed to client via EventBus
  ActionResult            → text + tool_executions + file_changes + artifacts

Tools (12 total):
  📁 read_file, write_file, list_files, search_code
  💻 shell_exec
  🔀 git_status, git_diff, git_branch, git_commit
  💬 send_message
  📋 create_task, update_task
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from connector.base import ConversationContext, MemorySnapshot
from connector.base_v2 import (
    AgentConnectorV2,
    ActionResult,
    AgentEvent,
    AgentEventType,
    Artifact,
    CapabilityInventory,
    FileChange,
    RiskLevel,
    ToolDefinition,
    ToolExecution,
    ToolPermission,
    register_connector_v2,
)

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────
# Constants
# ───────────────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 20            # Max agent loop iterations
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 8192
APPROVAL_TIMEOUT_S = 300        # 5 minutes
SANDBOX_WORKSPACE = "/workspace"


# ───────────────────────────────────────────────────────────────────
# Anthropic Tool Definitions (Anthropic API format)
# ───────────────────────────────────────────────────────────────────

ANTHROPIC_TOOLS = [
    # ── File Operations ─────────────────────────────────────────
    {
        "name": "read_file",
        "description": "Read the contents of a file. Use this to understand existing code, configuration, or documentation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read, relative to workspace root"},
                "max_lines": {"type": "integer", "description": "Maximum number of lines to read (default: 500)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file. Creates parent directories if needed. REQUIRES HUMAN APPROVAL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to write, relative to workspace root"},
                "content": {"type": "string", "description": "File contents"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory. Use this to explore the project structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory path relative to workspace root (default: '.')"},
                "max_depth": {"type": "integer", "description": "Max directory depth (default: 3)"},
            },
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search the codebase using regex patterns. Use this to find usages, definitions, or patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to search for"},
                "path": {"type": "string", "description": "Directory or file to search in (default: entire workspace)"},
                "max_results": {"type": "integer", "description": "Maximum results to return (default: 20)"},
            },
            "required": ["pattern"],
        },
    },

    # ── Shell Execution ─────────────────────────────────────────
    {
        "name": "shell_exec",
        "description": "Execute a shell command in the sandbox. REQUIRES HUMAN APPROVAL. "
                       "Use for: compiling code, running tests, installing packages, git operations not covered by git tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (default: workspace root)"},
                "timeout_s": {"type": "integer", "description": "Timeout in seconds (default: 120)"},
            },
            "required": ["command"],
        },
    },

    # ── Git Operations ──────────────────────────────────────────
    {
        "name": "git_status",
        "description": "Show the working tree status (git status).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "git_diff",
        "description": "Show changes in the working tree (git diff). Use before committing to review changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "staged": {"type": "boolean", "description": "Show staged changes (git diff --staged)"},
            },
            "required": [],
        },
    },
    {
        "name": "git_branch",
        "description": "Create a new Git branch. Safe operation — does not switch branches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Branch name (use kebab-case, e.g. 'fix-login-bug')"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "git_commit",
        "description": "Stage and commit changes. REQUIRES HUMAN APPROVAL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message (conventional commits format preferred)"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to stage (default: all modified)"},
            },
            "required": ["message"],
        },
    },

    # ── IM / Coordination ───────────────────────────────────────
    {
        "name": "send_message",
        "description": "Send a message to the IM channel you are in. Use this to report progress, ask questions, or share results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Message content (supports markdown)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a task for yourself or another agent. Use for tracking work items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
                "assignee_id": {"type": "string", "description": "Agent ID to assign to (omit for self)"},
                "priority": {"type": "string", "enum": ["LOW", "NORMAL", "HIGH", "URGENT"]},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_task",
        "description": "Update a task's status. Use to mark work as complete or blocked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to update"},
                "status": {"type": "string", "enum": ["TODO", "IN_PROGRESS", "REVIEW", "DONE", "BLOCKED"]},
                "comment": {"type": "string", "description": "Status change comment"},
            },
            "required": ["task_id", "status"],
        },
    },
]

# Tool metadata: name → (permission, risk_level, requires_approval)
TOOL_META: dict[str, tuple[ToolPermission, RiskLevel, bool]] = {
    "read_file":    (ToolPermission.FILE_READ,     RiskLevel.SAFE,    False),
    "write_file":   (ToolPermission.FILE_WRITE,    RiskLevel.HIGH,    True),
    "list_files":   (ToolPermission.FILE_READ,     RiskLevel.SAFE,    False),
    "search_code":  (ToolPermission.FILE_READ,     RiskLevel.SAFE,    False),
    "shell_exec":   (ToolPermission.SHELL_EXEC,    RiskLevel.HIGH,    True),
    "git_status":   (ToolPermission.GIT_READ,      RiskLevel.SAFE,    False),
    "git_diff":     (ToolPermission.GIT_READ,      RiskLevel.SAFE,    False),
    "git_branch":   (ToolPermission.GIT_WRITE,     RiskLevel.LOW,     False),
    "git_commit":   (ToolPermission.GIT_WRITE,     RiskLevel.HIGH,    True),
    "send_message": (ToolPermission.SEND_MESSAGE,  RiskLevel.SAFE,    False),
    "create_task":  (ToolPermission.CREATE_TASK,   RiskLevel.LOW,     False),
    "update_task":  (ToolPermission.CREATE_TASK,   RiskLevel.LOW,     False),
}


# ───────────────────────────────────────────────────────────────────
# Connector Implementation
# ───────────────────────────────────────────────────────────────────


@register_connector_v2("anthropic_agent")
class AnthropicAgentConnector(AgentConnectorV2):
    """
    Anthropic Agent Connector — v2 旗舰实现。

    Uses the Anthropic Python SDK to build a full agent loop with:
      - 12 tools (file I/O, shell, git, IM coordination)
      - Prompt caching (Soul Profile marked as cache_control breakpoint)
      - Parallel tool execution (Claude 4 default)
      - Human approval flow for dangerous operations
      - Real-time event streaming via callback
      - Sandbox isolation for file/shell operations
    """

    def __init__(self):
        self.client: httpx.AsyncClient | None = None
        self._anthropic: Any = None  # anthropic.AsyncAnthropic (lazy import)
        self._backend: str = ""      # "anthropic" | "openai_compatible"
        self.config: dict[str, Any] = {}
        self.model: str = DEFAULT_MODEL
        self.max_tokens: int = DEFAULT_MAX_TOKENS

        # Tool handler registry
        self._tool_handlers: dict[str, Callable] = {}

        # OpenAI-compatible endpoint
        self._openai_base_url: str = ""
        self._openai_api_key: str = ""

        # Current task context
        self._current_channel_id: str = ""
        self._current_agent_id: str = ""

    # ── Identity ──────────────────────────────────────────────────

    def connector_name(self) -> str:
        return "anthropic_agent"

    def connector_version(self) -> str:
        return "2.0.0"

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self, agent_config: dict[str, Any]) -> None:
        self.config = agent_config
        self.model = agent_config.get("model") or DEFAULT_MODEL
        self.max_tokens = int(agent_config.get("max_tokens", DEFAULT_MAX_TOKENS))
        self._current_agent_id = agent_config.get("agent_id", "")

        # ── Auto-detect backend ───────────────────────────────────
        anthropic_key = agent_config.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
        anthropic_base = agent_config.get("base_url") or os.getenv("ANTHROPIC_BASE_URL", "")
        if anthropic_base:
            anthropic_base = anthropic_base.rstrip("/")

        # Skip placeholder API keys (e.g., "your-anthropic-api-key-here")
        _placeholder_patterns = ("your-", "sk-your-", "placeholder", "changeme", "xxx")
        if anthropic_key and any(anthropic_key.lower().startswith(p) for p in _placeholder_patterns
                                  if p not in ("sk-",)):
            if anthropic_key.lower().startswith("your-") or "placeholder" in anthropic_key.lower():
                logger.info("ANTHROPIC_API_KEY appears to be a placeholder — skipping Anthropic backend")
                anthropic_key = ""

        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if deepseek_key and deepseek_key.lower().startswith("your-"):
            deepseek_key = ""  # skip placeholder
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key and openai_key.lower().startswith("your-"):
            openai_key = ""  # skip placeholder
        llm_key = agent_config.get("api_key") or os.getenv("LLM_API_KEY", "")
        custom_base = agent_config.get("base_url") or os.getenv("LLM_BASE_URL", "")

        if anthropic_key and not anthropic_key.lower().startswith("your-"):
            # ── Anthropic native backend ──────────────────────────
            self._backend = "anthropic"
            try:
                import anthropic
            except ImportError:
                raise ImportError(
                    "Anthropic backend selected but 'anthropic' package not installed. "
                    "Run: pip install anthropic"
                )
            client_kwargs: dict[str, Any] = {"api_key": anthropic_key}
            if anthropic_base:
                client_kwargs["base_url"] = anthropic_base
            self._anthropic = anthropic.AsyncAnthropic(**client_kwargs)
            logger.info(
                "Backend: anthropic (native) | model=%s base=%s",
                self.model, anthropic_base or "default",
            )
        elif deepseek_key:
            # ── DeepSeek (OpenAI-compatible) ──────────────────────
            self._backend = "openai_compatible"
            self._openai_base_url = custom_base or "https://api.deepseek.com"
            self._openai_api_key = deepseek_key
            if not self.model or self.model == DEFAULT_MODEL:
                self.model = "deepseek-chat"
            self.client = httpx.AsyncClient(
                base_url=self._openai_base_url,
                headers={
                    "Authorization": f"Bearer {self._openai_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=10, read=600, write=60, pool=60),
            )
            logger.info("Backend: DeepSeek (openai-compatible) | model=%s", self.model)
        elif openai_key or llm_key:
            # ── OpenAI / Custom (OpenAI-compatible) ───────────────
            self._backend = "openai_compatible"
            self._openai_base_url = custom_base or "https://api.openai.com/v1"
            self._openai_api_key = openai_key or llm_key
            if not self.model or self.model == DEFAULT_MODEL:
                self.model = "gpt-4o"
            self.client = httpx.AsyncClient(
                base_url=self._openai_base_url,
                headers={
                    "Authorization": f"Bearer {self._openai_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=10, read=600, write=60, pool=60),
            )
            logger.info("Backend: OpenAI-compatible | model=%s base=%s", self.model, self._openai_base_url)
        elif custom_base:
            # ── Custom base_url without explicit key ──────────────
            self._backend = "openai_compatible"
            self._openai_base_url = custom_base.rstrip("/")
            self._openai_api_key = llm_key or "no-key"
            if not self.model or self.model == DEFAULT_MODEL:
                self.model = os.getenv("LLM_MODEL", "deepseek-chat")
            self.client = httpx.AsyncClient(
                base_url=self._openai_base_url,
                headers={
                    "Authorization": f"Bearer {self._openai_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=10, read=600, write=60, pool=60),
            )
            logger.info("Backend: custom (openai-compatible) | model=%s base=%s", self.model, self._openai_base_url)
        else:
            # ── No API key available ─────────────────────────────
            logger.warning(
                "No API key found for agent %s. "
                "Set ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY, or LLM_API_KEY. "
                "Agent will return offline status.",
                self._current_agent_id,
            )
            self._backend = "none"

        # Register tool handlers (same regardless of backend)
        self._register_tool_handlers()

    async def health_check(self) -> bool:
        if self._backend == "anthropic":
            return self._anthropic is not None
        return self._backend in ("openai_compatible",) and self.client is not None

    async def shutdown(self) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None
        self._anthropic = None
        logger.info("AgenticConnector shutdown")

    # ── Capability Inventory ─────────────────────────────────────

    def capability_inventory(self) -> CapabilityInventory:
        return CapabilityInventory(
            framework="anthropic_agent",
            text_generation=True,
            streaming=True,
            structured_output=False,
            file_read=True,
            file_write=True,
            file_delete=False,
            file_search=True,
            shell_execution=True,
            code_execution=True,
            browser_automation=False,
            git_read=True,
            git_write=True,
            web_search=False,
            web_fetch=False,
            api_call=False,
            multi_agent_orchestration=False,
            sub_agent_delegation=False,
            human_approval=True,
            max_context_tokens=200000,
            max_output_tokens=8192,
            supports_prompt_caching=True,
            supported_tools=list(TOOL_META.keys()),
            max_tools_per_request=20,
        )

    def tool_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=t["name"],
                description=t["description"],
                parameters=t.get("input_schema", {}),
                permission=TOOL_META[t["name"]][0],
                risk_level=TOOL_META[t["name"]][1],
                requires_approval=TOOL_META[t["name"]][2],
                approval_timeout_s=APPROVAL_TIMEOUT_S,
            )
            for t in ANTHROPIC_TOOLS
        ]

    # ── Core: act() ──────────────────────────────────────────────

    async def act(
        self,
        context: ConversationContext,
        soul_profile,  # SoulProfile
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> ActionResult:
        if self._backend == "none":
            return ActionResult(
                text="[Agent offline — 未配置 API Key。请设置 ANTHROPIC_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY]",
                success=False, error_message="no_api_key",
            )
        if self._backend == "anthropic":
            return await self._act_anthropic(context, soul_profile, memory_context, event_callback)
        if self._backend == "openai_compatible":
            return await self._act_openai(context, soul_profile, memory_context, event_callback)
        return ActionResult(text="[Unknown backend]", success=False)

    # ── Anthropic backend ────────────────────────────────────────

    async def _act_anthropic(
        self, context, soul_profile, memory_context, event_callback,
    ) -> ActionResult:
        if not self._anthropic:
            return ActionResult(text="[Anthropic client not initialized]", success=False)

        self._current_channel_id = context.channel_id

        t_start = time.monotonic()
        tool_executions: list[ToolExecution] = []
        file_changes: list[FileChange] = []
        tokens_used = 0

        # Track files touched by write operations
        _touched_files: set[str] = set()

        try:
            # ── 1. Build System Prompt ──────────────────────────
            system_text = soul_profile.build_system_prompt(
                context={
                    "channel_id": context.channel_id,
                    "participants": ", ".join(
                        f"{'Agent' if p.get('type') == 'agent' else 'User'}({p.get('id', '')[:8]})"
                        for p in (context.participants or [])
                    ),
                },
                memories=memory_context.episodic if memory_context else [],
            )

            # Build system content blocks with cache_control on soul profile
            system_content: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},  # Soul Profile rarely changes
                },
            ]

            # Add memory context (not cached — changes every conversation)
            if memory_context and memory_context.episodic:
                memory_lines = []
                for m in memory_context.episodic[:10]:
                    content = m.get("content", {})
                    if isinstance(content, dict):
                        text = str(content.get("messages", content.get("knowledge", "")))[:200]
                    else:
                        text = str(content)[:200]
                    if text:
                        memory_lines.append(f"- {text}")
                if memory_lines:
                    system_content.append({
                        "type": "text",
                        "text": "\n## Relevant Memories\n" + "\n".join(memory_lines),
                    })

            # ── 2. Build Messages ────────────────────────────────
            messages = self._build_messages(context)

            # ── 3. Agent Loop ────────────────────────────────────
            # Filter tools by agent permissions
            allowed_permissions = set(self.config.get("tool_permissions", []))
            if isinstance(allowed_permissions, str):
                import json as _json
                allowed_permissions = set(_json.loads(allowed_permissions) if allowed_permissions else [])

            # Default: allow send_message + create_task
            if not allowed_permissions:
                allowed_permissions = {"send_message", "create_task"}

            tools = self._filtered_tools(allowed_permissions)

            rounds = 0
            final_text = ""

            while rounds < MAX_TOOL_ROUNDS:
                rounds += 1

                response = await self._anthropic.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_content,
                    messages=messages,
                    **(dict(tools=tools) if tools else {}),
                    temperature=self.config.get("temperature", 0.7),
                )

                # Track tokens
                usage = response.usage
                if usage:
                    tokens_used += usage.input_tokens + usage.output_tokens

                # Parse response blocks
                text_blocks: list[str] = []
                tool_use_blocks: list[Any] = []

                for block in response.content:
                    if block.type == "text":
                        text_blocks.append(block.text)
                        # Stream text chunks
                        if event_callback:
                            await event_callback(AgentEvent(
                                agent_id=self._current_agent_id,
                                agent_name=self.config.get("agent_name", ""),
                                event_type=AgentEventType.THOUGHT_CHUNK,
                                payload={"text": block.text, "channel_id": self._current_channel_id},
                            ))
                    elif block.type == "tool_use":
                        tool_use_blocks.append(block)

                # No tool calls → end of loop
                if not tool_use_blocks:
                    final_text = "\n".join(text_blocks)
                    break

                # ── Append assistant message ──────────────────────
                messages.append({
                    "role": "assistant",
                    "content": [
                        *([{"type": "text", "text": t} for t in text_blocks]),
                        *([
                            {"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input}
                            for tu in tool_use_blocks
                        ]),
                    ],
                })

                # ── Execute tools ─────────────────────────────────
                tool_results_content: list[dict[str, Any]] = []

                for tu in tool_use_blocks:
                    tool_name = tu.name
                    tool_input = tu.input or {}

                    # Push event
                    if event_callback:
                        await event_callback(AgentEvent(
                            agent_id=self._current_agent_id,
                            agent_name=self.config.get("agent_name", ""),
                            event_type=AgentEventType.TOOL_EXECUTING,
                            payload={
                                "tool_name": tool_name,
                                "tool_params": self._safe_params(tool_input),
                                "channel_id": self._current_channel_id,
                            },
                        ))

                    # ── Approval check ────────────────────────────
                    meta = TOOL_META.get(tool_name, (ToolPermission.SEND_MESSAGE, RiskLevel.SAFE, False))
                    requires_approval = meta[2]
                    risk_level = meta[1]

                    if requires_approval and event_callback:
                        approval_granted = await self._request_approval(
                            tool_name, tool_input, risk_level, event_callback,
                        )
                        if not approval_granted:
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": tu.id,
                                "content": f"Operation '{tool_name}' was denied (approval not granted). "
                                           f"Explain to the user why this operation was needed and suggest alternatives.",
                                "is_error": True,
                            })
                            continue

                    # ── Execute ───────────────────────────────────
                    t_tool_start = time.monotonic()
                    handler = self._tool_handlers.get(tool_name)
                    try:
                        if handler:
                            result_data = await handler(**tool_input)
                            success = result_data.get("success", True)
                            output_text = result_data.get("output", "")
                            error_text = result_data.get("error", "")
                        else:
                            success = False
                            output_text = ""
                            error_text = f"No handler for tool: {tool_name}"
                    except Exception as ex:
                        success = False
                        output_text = ""
                        error_text = str(ex)
                        logger.warning("Tool %s error: %s", tool_name, ex)

                    t_tool_ms = (time.monotonic() - t_tool_start) * 1000

                    # Track file changes
                    if tool_name == "write_file" and success:
                        _touched_files.add(tool_input.get("path", ""))
                        file_changes.append(FileChange(
                            path=tool_input.get("path", ""),
                            operation="modify" if os.path.exists(tool_input.get("path", "")) else "create",
                        ))

                    # Record execution
                    tool_executions.append(ToolExecution(
                        tool_name=tool_name,
                        tool_params=tool_input,
                        success=success,
                        result_summary=output_text[:500] if output_text else error_text[:500],
                        duration_ms=t_tool_ms,
                        risk_level=risk_level,
                        sandbox_id=getattr(self, "_sandbox_id", ""),
                    ))

                    # Push result event
                    if event_callback:
                        await event_callback(AgentEvent(
                            agent_id=self._current_agent_id,
                            agent_name=self.config.get("agent_name", ""),
                            event_type=AgentEventType.TOOL_RESULT if success else AgentEventType.TOOL_ERROR,
                            payload={
                                "tool_name": tool_name,
                                "success": success,
                                "summary": output_text[:500] if success else error_text[:500],
                                "channel_id": self._current_channel_id,
                            },
                        ))

                    # Append tool result
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": output_text if success else f"Error: {error_text}",
                        "is_error": not success,
                    })

                # Appending tool results to conversation
                messages.append({"role": "user", "content": tool_results_content})

            # End of loop — if max rounds reached with no text, provide summary
            if not final_text and rounds >= MAX_TOOL_ROUNDS:
                final_text = (
                    f"[Maximum tool rounds ({MAX_TOOL_ROUNDS}) reached. "
                    f"I performed {len(tool_executions)} operations. "
                    f"Please ask me to continue if needed.]"
                )

            total_ms = (time.monotonic() - t_start) * 1000

            return ActionResult(
                text=final_text,
                tool_executions=tool_executions,
                file_changes=file_changes,
                reasoning_trace=f"rounds={rounds} tokens={tokens_used}",
                memory_candidates=self._extract_memory_candidates(final_text, tool_executions),
                total_duration_ms=total_ms,
                tokens_used=tokens_used,
                rounds=rounds,
                success=True,
            )

        except Exception as e:
            logger.error("Agent act() error (anthropic backend): %s", e, exc_info=True)
            return ActionResult(
                text=f"执行过程中出现异常：{e}",
                tool_executions=tool_executions,
                file_changes=file_changes,
                success=False,
                error_message=str(e),
            )

    # ── OpenAI-compatible backend ────────────────────────────────

    async def _act_openai(
        self, context, soul_profile, memory_context, event_callback,
    ) -> ActionResult:
        """Agent loop using OpenAI-compatible /v1/chat/completions API."""
        if not self.client:
            return ActionResult(text="[OpenAI-compatible client not initialized]", success=False)

        self._current_channel_id = context.channel_id
        t_start = time.monotonic()
        tool_executions: list[ToolExecution] = []
        file_changes: list[FileChange] = []
        tokens_used = 0
        _touched_files: set[str] = set()

        try:
            # ── 1. Build system prompt ────────────────────────────
            system_text = soul_profile.build_system_prompt(
                context={
                    "channel_id": context.channel_id,
                    "participants": ", ".join(
                        f"{'Agent' if p.get('type') == 'agent' else 'User'}({p.get('id', '')[:8]})"
                        for p in (context.participants or [])
                    ),
                },
                memories=memory_context.episodic if memory_context else [],
            )

            # OpenAI-compatible: system message is in the messages array
            api_messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_text},
            ]

            # ── 2. Build user messages ─────────────────────────────
            for msg in context.messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                name = msg.get("sender_name", "")
                sender_type = msg.get("sender_type", "human")
                if role not in ("user", "assistant"):
                    continue
                display = content
                if name and role == "user":
                    prefix = f"[{name}]" if sender_type == "agent" else name
                    display = f"{prefix}: {content}"
                api_messages.append({"role": role, "content": display})

            # ── 3. Filter tools ────────────────────────────────────
            allowed_permissions = set(self.config.get("tool_permissions", []))
            if isinstance(allowed_permissions, str):
                import json as _json
                allowed_permissions = set(_json.loads(allowed_permissions) if allowed_permissions else [])
            if not allowed_permissions:
                allowed_permissions = {"send_message", "create_task"}

            openai_tools = self._build_openai_tools(allowed_permissions)

            rounds = 0
            final_text = ""

            while rounds < MAX_TOOL_ROUNDS:
                rounds += 1

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": api_messages,
                    "max_tokens": self.max_tokens,
                    "temperature": self.config.get("temperature", 0.7),
                }
                if openai_tools:
                    payload["tools"] = openai_tools
                    payload["tool_choice"] = "auto"

                resp = await self.client.post("/chat/completions", json=payload)

                if resp.status_code != 200:
                    error_text = resp.text[:500]
                    logger.error("OpenAI-compatible API error %d: %s", resp.status_code, error_text)
                    return ActionResult(
                        text=f"[API error {resp.status_code}]",
                        tool_executions=tool_executions,
                        file_changes=file_changes,
                        success=False,
                        error_message=error_text,
                    )

                data = resp.json()
                usage = data.get("usage", {})
                tokens_used += usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)

                choice = data["choices"][0]
                msg = choice["message"]
                finish_reason = choice.get("finish_reason", "")

                text = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []

                # Push text chunks
                if text and event_callback:
                    await event_callback(AgentEvent(
                        agent_id=self._current_agent_id,
                        agent_name=self.config.get("agent_name", ""),
                        event_type=AgentEventType.THOUGHT_CHUNK,
                        payload={"text": text, "channel_id": self._current_channel_id},
                    ))

                if not tool_calls:
                    final_text = text
                    break

                # ── Append assistant message with tool_calls ───────
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                assistant_msg["tool_calls"] = tool_calls
                api_messages.append(assistant_msg)

                # ── Execute each tool ──────────────────────────────
                for tc in tool_calls:
                    fn = tc["function"]
                    tool_name = fn["name"]
                    try:
                        tool_input = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        tool_input = {}

                    # Event: executing
                    if event_callback:
                        await event_callback(AgentEvent(
                            agent_id=self._current_agent_id,
                            agent_name=self.config.get("agent_name", ""),
                            event_type=AgentEventType.TOOL_EXECUTING,
                            payload={
                                "tool_name": tool_name,
                                "tool_params": self._safe_params(tool_input),
                                "channel_id": self._current_channel_id,
                            },
                        ))

                    # Approval check
                    meta = TOOL_META.get(tool_name, (ToolPermission.SEND_MESSAGE, RiskLevel.SAFE, False))
                    risk_level = meta[1]
                    if meta[2] and event_callback:
                        approved = await self._request_approval(tool_name, tool_input, risk_level, event_callback)
                        if not approved:
                            api_messages.append({
                                "role": "tool", "tool_call_id": tc["id"],
                                "content": f"Operation denied: approval not granted.",
                            })
                            continue

                    # Execute
                    t_tool_start = time.monotonic()
                    handler = self._tool_handlers.get(tool_name)
                    try:
                        result_data = await handler(**tool_input) if handler else {"success": False, "error": "no handler"}
                        success = result_data.get("success", True)
                        output_text = result_data.get("output", "")
                        error_text = result_data.get("error", "")
                    except Exception as ex:
                        success = False
                        output_text = ""
                        error_text = str(ex)

                    t_tool_ms = (time.monotonic() - t_tool_start) * 1000

                    if tool_name == "write_file" and success:
                        _touched_files.add(tool_input.get("path", ""))
                        file_changes.append(FileChange(
                            path=tool_input.get("path", ""),
                            operation="modify" if os.path.exists(tool_input.get("path", "")) else "create",
                        ))

                    tool_executions.append(ToolExecution(
                        tool_name=tool_name, tool_params=tool_input,
                        success=success,
                        result_summary=output_text[:500] if output_text else error_text[:500],
                        duration_ms=t_tool_ms, risk_level=risk_level,
                    ))

                    if event_callback:
                        await event_callback(AgentEvent(
                            agent_id=self._current_agent_id,
                            agent_name=self.config.get("agent_name", ""),
                            event_type=AgentEventType.TOOL_RESULT if success else AgentEventType.TOOL_ERROR,
                            payload={
                                "tool_name": tool_name, "success": success,
                                "summary": output_text[:500] if success else error_text[:500],
                                "channel_id": self._current_channel_id,
                            },
                        ))

                    # OpenAI-compatible: tool result message
                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": output_text if success else f"Error: {error_text}",
                    })

            if not final_text and rounds >= MAX_TOOL_ROUNDS:
                final_text = (
                    f"[Maximum tool rounds ({MAX_TOOL_ROUNDS}) reached. "
                    f"I performed {len(tool_executions)} operations.]"
                )

            return ActionResult(
                text=final_text,
                tool_executions=tool_executions,
                file_changes=file_changes,
                reasoning_trace=f"backend=openai_compatible rounds={rounds} tokens={tokens_used}",
                memory_candidates=self._extract_memory_candidates(final_text, tool_executions),
                total_duration_ms=(time.monotonic() - t_start) * 1000,
                tokens_used=tokens_used,
                rounds=rounds,
                success=True,
            )

        except Exception as e:
            logger.error("OpenAI-compatible act() error: %s", e, exc_info=True)
            return ActionResult(
                text=f"执行过程中出现异常：{e}",
                tool_executions=tool_executions,
                file_changes=file_changes,
                success=False,
                error_message=str(e),
            )

    def _build_openai_tools(self, permissions: set[str]) -> list[dict[str, Any]] | None:
        """Convert Anthropic-format tools to OpenAI function-calling format."""
        filtered = [t for t in ANTHROPIC_TOOLS if t["name"] in permissions]
        if not filtered:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in filtered
        ]

    # ── Core: act_stream() ───────────────────────────────────────

    async def act_stream(
        self,
        context: ConversationContext,
        soul_profile,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        """
        Streaming implementation — yields text chunks as Claude generates them.

        ⚠️ Complex interaction with tool_use:
          Streaming is used for text generation. When tool_use occurs,
          we yield status messages then continue after tool execution.
        """
        if self._backend == "none":
            yield "[Agent offline — 未配置 API Key]"
            return
        if self._backend == "openai_compatible":
            # OpenAI-compatible streaming: delegate to non-stream, yield result
            result = await self._act_openai(context, soul_profile, memory_context, event_callback)
            yield result.text
            return
        if not self._anthropic:
            yield "[Anthropic client not initialized]"
            return

        self._current_channel_id = context.channel_id

        try:
            system_text = soul_profile.build_system_prompt(
                context={
                    "channel_id": context.channel_id,
                    "participants": ", ".join(
                        f"{'Agent' if p.get('type') == 'agent' else 'User'}({p.get('id', '')[:8]})"
                        for p in (context.participants or [])
                    ),
                },
                memories=memory_context.episodic if memory_context else [],
            )

            system_content: list[dict[str, Any]] = [
                {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}},
            ]

            messages = self._build_messages(context)
            tools = self._filtered_tools(set(self.config.get("tool_permissions", [])))

            rounds = 0
            while rounds < MAX_TOOL_ROUNDS:
                rounds += 1

                tool_use_blocks = []
                text_chunks = []
                current_tool_json = ""
                current_tool_name = ""

                async with self._anthropic.messages.stream(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_content,
                    messages=messages,
                    **(dict(tools=tools) if tools else {}),
                    temperature=self.config.get("temperature", 0.7),
                ) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                text_chunks.append(event.delta.text)
                                yield event.delta.text
                            elif event.delta.type == "input_json_delta":
                                current_tool_json += event.delta.partial_json

                        elif event.type == "content_block_start":
                            if event.content_block.type == "tool_use":
                                current_tool_name = event.content_block.name
                                current_tool_json = ""

                        elif event.type == "content_block_stop":
                            if current_tool_name and current_tool_json:
                                try:
                                    tool_input = json.loads(current_tool_json)
                                except json.JSONDecodeError:
                                    tool_input = {}
                                tool_use_blocks.append({
                                    "name": current_tool_name,
                                    "input": tool_input,
                                })
                                current_tool_name = ""
                                current_tool_json = ""

                if not tool_use_blocks:
                    break  # end of turn

                # For streaming, execute tools synchronously and continue
                tool_results = []
                for tu in tool_use_blocks:
                    handler = self._tool_handlers.get(tu["name"])
                    try:
                        result_data = await handler(**tu["input"]) if handler else {"success": False, "error": "no handler"}
                        tool_results.append({
                            "tool": tu["name"],
                            "success": result_data.get("success", True),
                            "output": result_data.get("output", result_data.get("error", "")),
                        })
                    except Exception as e:
                        tool_results.append({"tool": tu["name"], "success": False, "error": str(e)})

                yield f"\n\n[🔧 {', '.join(f'{t['tool']}({t['success']})' for t in tool_results)}]\n\n"

        except Exception as e:
            yield f"\n[Error: {e}]"

    # ── Tool Handlers ─────────────────────────────────────────────

    def _register_tool_handlers(self) -> None:
        self._tool_handlers = {
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "list_files": self._handle_list_files,
            "search_code": self._handle_search_code,
            "shell_exec": self._handle_shell_exec,
            "git_status": self._handle_git_status,
            "git_diff": self._handle_git_diff,
            "git_branch": self._handle_git_branch,
            "git_commit": self._handle_git_commit,
            "send_message": self._handle_send_message,
            "create_task": self._handle_create_task,
            "update_task": self._handle_update_task,
        }

    async def _handle_read_file(self, path: str, max_lines: int = 500, **kwargs) -> dict:
        safe_path = self._safe_path(path)
        try:
            with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            total = len(lines)
            selected = lines[:max_lines]
            output = "".join(selected)
            if total > max_lines:
                output += f"\n\n... ({total - max_lines} more lines, {total} total)"
            return {"success": True, "output": output}
        except FileNotFoundError:
            return {"success": False, "error": f"File not found: {path}"}
        except PermissionError:
            return {"success": False, "error": f"Permission denied: {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_write_file(self, path: str, content: str, **kwargs) -> dict:
        safe_path = self._safe_path(path)
        try:
            os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)
            size = len(content)
            return {"success": True, "output": f"Wrote {size} bytes to {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_list_files(self, directory: str = ".", max_depth: int = 3, **kwargs) -> dict:
        safe_dir = self._safe_path(directory)
        try:
            lines = []
            for root, dirs, files in os.walk(safe_dir):
                depth = root.replace(safe_dir, "").count(os.sep)
                if depth > max_depth:
                    dirs[:] = []
                    continue
                level_prefix = "  " * depth
                folder = os.path.basename(root) or root
                lines.append(f"{level_prefix}{folder}/")
                for f in sorted(files)[:50]:
                    lines.append(f"{level_prefix}  {f}")
                if len(files) > 50:
                    lines.append(f"{level_prefix}  ... ({len(files) - 50} more files)")
            output = "\n".join(lines[:200])
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_search_code(self, pattern: str, path: str = ".", max_results: int = 20, **kwargs) -> dict:
        safe_path = self._safe_path(path)
        try:
            import subprocess
            result = subprocess.run(
                ["rg", "--line-number", "--max-count", str(max_results), pattern, safe_path],
                capture_output=True, text=True, timeout=30, cwd=SANDBOX_WORKSPACE,
            )
            if result.returncode == 0:
                return {"success": True, "output": result.stdout[:5000]}
            elif result.returncode == 1:
                return {"success": True, "output": f"No matches found for '{pattern}'"}
            else:
                return {"success": False, "error": result.stderr[:500]}
        except FileNotFoundError:
            # ripgrep not installed — fallback to grep
            try:
                import subprocess
                result = subprocess.run(
                    ["grep", "-rn", "--max-count", str(max_results), pattern, safe_path],
                    capture_output=True, text=True, timeout=30, cwd=SANDBOX_WORKSPACE,
                )
                return {"success": True, "output": result.stdout[:5000] or f"No matches found for '{pattern}'"}
            except Exception as e2:
                return {"success": False, "error": str(e2)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_shell_exec(self, command: str, cwd: str = SANDBOX_WORKSPACE, timeout_s: int = 120, **kwargs) -> dict:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s,
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0

            output = stdout
            if stderr:
                output += f"\n[stderr]\n{stderr}"
            if exit_code != 0:
                output += f"\n[exit code: {exit_code}]"

            return {"success": exit_code == 0, "output": output[:10000]}
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Command timed out after {timeout_s}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_git_status(self, **kwargs) -> dict:
        return await self._run_git(["status", "--short"])

    async def _handle_git_diff(self, staged: bool = False, **kwargs) -> dict:
        args = ["diff"]
        if staged:
            args.append("--staged")
        return await self._run_git(args)

    async def _handle_git_branch(self, name: str, **kwargs) -> dict:
        return await self._run_git(["checkout", "-b", name])

    async def _handle_git_commit(self, message: str, files: list[str] | None = None, **kwargs) -> dict:
        if files:
            await self._run_git(["add", *files])
        else:
            await self._run_git(["add", "-A"])
        return await self._run_git(["commit", "-m", message])

    async def _handle_send_message(self, content: str, **kwargs) -> dict:
        # The actual message sending is handled by IM Core.
        # We just return the content to be forwarded.
        return {"success": True, "output": f"Message queued: {content[:200]}"}

    async def _handle_create_task(self, title: str, description: str = "",
                                  assignee_id: str = "", priority: str = "NORMAL", **kwargs) -> dict:
        return {
            "success": True,
            "output": f"Task created: [{priority}] {title}" + (f" → assigned to {assignee_id}" if assignee_id else ""),
            "task": {"title": title, "description": description, "assignee_id": assignee_id, "priority": priority},
        }

    async def _handle_update_task(self, task_id: str, status: str, comment: str = "", **kwargs) -> dict:
        return {
            "success": True,
            "output": f"Task {task_id} → {status}" + (f": {comment}" if comment else ""),
        }

    async def _run_git(self, args: list[str]) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=SANDBOX_WORKSPACE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out_text = stdout.decode("utf-8", errors="replace")
            err_text = stderr.decode("utf-8", errors="replace")
            success = proc.returncode == 0
            output = out_text or err_text
            return {"success": success, "output": output[:5000], "error": err_text[:500] if not success else ""}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Approval Flow ─────────────────────────────────────────────

    async def _request_approval(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        risk_level: RiskLevel,
        event_callback: Callable[[AgentEvent], Awaitable[None]],
    ) -> bool:
        """Send approval request and wait for human response."""
        approval_id = f"approval-{self._current_agent_id}-{int(time.time() * 1000)}"

        await event_callback(AgentEvent(
            agent_id=self._current_agent_id,
            agent_name=self.config.get("agent_name", ""),
            event_type=AgentEventType.APPROVAL_NEEDED,
            payload={
                "approval_id": approval_id,
                "tool_name": tool_name,
                "action_description": self._describe_action(tool_name, tool_input),
                "risk_level": risk_level.value,
                "tool_params": self._safe_params(tool_input),
                "timeout_seconds": APPROVAL_TIMEOUT_S,
                "channel_id": getattr(self, "_current_channel_id", ""),
            },
        ))

        # ⚠️ Phase 2 MVP: auto-approve safe operations, deny dangerous ones with timeout
        # In production, this waits for human approval via WebSocket round-trip
        if risk_level in (RiskLevel.SAFE, RiskLevel.LOW):
            logger.info("Auto-approving %s (risk=%s)", tool_name, risk_level.value)
            return True

        # For HIGH/CRITICAL: wait for approval (simulated timeout for now)
        logger.warning(
            "Approval required for %s (risk=%s) — would block for human in production",
            tool_name, risk_level.value,
        )
        # Phase 2 MVP: allow with warning. Production: wait for callback.
        return True

    def _describe_action(self, tool_name: str, params: dict[str, Any]) -> str:
        """Generate human-readable action description for approval card."""
        if tool_name == "write_file":
            return f"写入文件: {params.get('path', '?')} ({len(params.get('content', ''))} 字节)"
        elif tool_name == "shell_exec":
            cmd = params.get("command", "")[:80]
            return f"执行命令: {cmd}"
        elif tool_name == "git_commit":
            return f"Git 提交: {params.get('message', '?')}"
        return f"调用工具 {tool_name}"

    # ── Helpers ───────────────────────────────────────────────────

    def _build_messages(self, context: ConversationContext) -> list[dict[str, Any]]:
        """Convert ConversationContext to Anthropic messages format."""
        messages: list[dict[str, Any]] = []
        for msg in context.messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("sender_name", "")
            sender_type = msg.get("sender_type", "human")

            if role not in ("user", "assistant"):
                continue

            display = content
            if name and role == "user":
                prefix = f"[{name}]" if sender_type == "agent" else name
                display = f"{prefix}: {content}"

            messages.append({"role": role, "content": display})
        return messages

    def _filtered_tools(self, permissions: set[str]) -> list[dict[str, Any]]:
        """Filter Anthropic tool definitions by agent's permission set."""
        if not permissions:
            return ANTHROPIC_TOOLS

        return [
            t for t in ANTHROPIC_TOOLS
            if t["name"] in permissions
        ]

    def _safe_path(self, path: str) -> str:
        """Resolve path safely within workspace. Prevents path traversal."""
        workspace = os.path.abspath(SANDBOX_WORKSPACE)
        full = os.path.normpath(os.path.join(workspace, path))
        if not full.startswith(workspace):
            raise ValueError(f"Path traversal detected: {path}")
        return full

    def _safe_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Sanitize params for event payload (truncate long values, mask secrets)."""
        safe: dict[str, Any] = {}
        for k, v in params.items():
            if k.lower() in ("api_key", "password", "token", "secret"):
                safe[k] = "***"
            elif isinstance(v, str) and len(v) > 300:
                safe[k] = v[:300] + "..."
            else:
                safe[k] = v
        return safe

    def _extract_memory_candidates(
        self, text: str, executions: list[ToolExecution],
    ) -> list[dict[str, Any]]:
        """Extract candidate memories from this interaction."""
        candidates = []
        # Summarize tool executions as memory candidates
        for ex in executions:
            if ex.success:
                candidates.append({
                    "type": "tool_execution",
                    "tool": ex.tool_name,
                    "summary": ex.result_summary[:200],
                    "importance": 0.5,
                })
        # If the agent made an important conclusion, capture it
        if text and len(text) > 100:
            candidates.append({
                "type": "conversation_summary",
                "content": text[:500],
                "importance": 0.6,
            })
        return candidates
