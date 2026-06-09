"""
ClaudeCodeCLIConnector — v2 Connector using the Claude Code CLI via subprocess.

Unlike AnthropicAgentConnector (which calls the Anthropic API directly),
this connector spawns the real `claude` CLI tool as a subprocess and
parses its JSON output. This gives us the FULL Claude Code harness —
200K context, prompt caching, parallel tool use, thinking mode — all
the engineering that Anthropic put into their CLI product.

Mode: one-shot (`-p` / `--print`)
Output: `--output-format json`
Soul: `--system-prompt` (injected from SoulSerializer)
Tools: `--allowedTools` (filtered by agent permissions)
Max turns: `--max-turns` (configurable)
Model: `--model` (from agent config)

Prerequisites:
  - Claude Code CLI must be installed and in PATH (`claude --version`)
  - ANTHROPIC_API_KEY or equivalent must be configured
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from typing import Any, AsyncIterator, Awaitable, Callable

from connector.base import ConversationContext, MemorySnapshot
from connector.base_v2 import (
    AgentConnectorV2,
    ActionResult,
    AgentEvent,
    AgentEventType,
    CapabilityInventory,
    ToolDefinition,
    ToolPermission,
    RiskLevel,
    register_connector_v2,
)

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────
# Constants
# ───────────────────────────────────────────────────────────────────

DEFAULT_MAX_TURNS = 15
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT_S = 600  # 10 minute max for a single act()
CLAUDE_BIN = "claude"


# Permission mode mapping
PERMISSION_MODES = {
    "auto": "auto",              # Auto-approve safe ops
    "acceptEdits": "acceptEdits",# Auto-approve edits
    "plan": "plan",              # Show plan, ask for approval
    "bypassPermissions": "bypassPermissions",  # Full auto (use carefully)
    "default": "default",
}


# ───────────────────────────────────────────────────────────────────
# Connector Implementation
# ───────────────────────────────────────────────────────────────────


@register_connector_v2("claude_code_cli")
class ClaudeCodeCLIConnector(AgentConnectorV2):
    """
    Claude Code CLI Connector — subprocess-based integration.

    Spawns `claude -p "message" --output-format json ...` as a subprocess,
    injects Soul Profile via --system-prompt, and parses the structured
    JSON output into ActionResult.

    Key benefits over AnthropicAgentConnector:
      - Full Claude Code harness (thinking mode, parallel tools, caching)
      - No need to write our own agent loop
      - Works with any LLM backend Claude Code supports (via --model)
      - CLI is battle-tested by Anthropic

    Limitations:
      - Subprocess overhead (~200ms spawn time)
      - No real-time streaming during execution (only final JSON parse)
      - Requires `claude` binary in PATH
    """

    def __init__(self):
        self.config: dict[str, Any] = {}
        self._agent_id: str = ""
        self._agent_name: str = ""
        self._model: str = DEFAULT_MODEL
        self._max_turns: int = DEFAULT_MAX_TURNS
        self._permission_mode: str = "plan"
        self._workspace_dir: str = ""
        self._claude_bin: str = CLAUDE_BIN

        # Check availability
        self._available = shutil.which(CLAUDE_BIN) is not None

    # ── Identity ──────────────────────────────────────────────────

    def connector_name(self) -> str:
        return "claude_code_cli"

    def connector_version(self) -> str:
        return "1.0.0"

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self, agent_config: dict[str, Any]) -> None:
        self.config = agent_config
        self._agent_id = agent_config.get("agent_id", "")
        self._agent_name = agent_config.get("agent_name", "")
        self._model = agent_config.get("model") or DEFAULT_MODEL
        self._max_turns = int(agent_config.get("max_turns", DEFAULT_MAX_TURNS))
        self._permission_mode = agent_config.get("permission_mode", "plan")
        self._workspace_dir = agent_config.get("workspace_dir", os.getcwd())

        if not self._available:
            self._available = shutil.which(CLAUDE_BIN) is not None

        if self._available:
            logger.info(
                "ClaudeCodeCLIConnector initialized: agent=%s model=%s max_turns=%d "
                "permission=%s cwd=%s",
                self._agent_id, self._model, self._max_turns,
                self._permission_mode, self._workspace_dir,
            )
        else:
            logger.warning(
                "ClaudeCodeCLIConnector: `claude` binary not found in PATH. "
                "Agent %s will return offline status. "
                "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code",
                self._agent_id,
            )

    async def health_check(self) -> bool:
        if not self._available:
            return False
        try:
            proc = await asyncio.create_subprocess_shell(
                f"{self._claude_bin} --version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except Exception:
            return False

    async def shutdown(self) -> None:
        logger.info("ClaudeCodeCLIConnector shutdown")

    # ── Capability Inventory ─────────────────────────────────────

    def capability_inventory(self) -> CapabilityInventory:
        inv = CapabilityInventory(
            framework="claude_code_cli",
            text_generation=True,
            streaming=False,  # CLI subprocess, no real-time streaming
            structured_output=True,  # JSON output format
            file_read=True,
            file_write=True,
            file_delete=True,
            file_search=True,
            shell_execution=True,
            code_execution=True,
            browser_automation=False,
            git_read=True,
            git_write=True,
            web_search=False,
            web_fetch=False,
            multi_agent_orchestration=False,
            sub_agent_delegation=False,
            human_approval=True,
            max_context_tokens=200000,
            max_output_tokens=32000,
            supports_prompt_caching=True,
            supported_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
            max_tools_per_request=50,
        )
        if not self._available:
            inv.extra["status"] = "offline"
            inv.extra["install_hint"] = (
                "Claude Code CLI not found in PATH. "
                "Install: https://docs.anthropic.com/en/docs/claude-code"
            )
        return inv

    def tool_definitions(self) -> list[ToolDefinition]:
        """Claude Code CLI built-in tools."""
        return [
            ("Bash", "Execute shell commands", ToolPermission.SHELL_EXEC, RiskLevel.HIGH, True),
            ("Read", "Read file contents", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
            ("Write", "Write or create a file", ToolPermission.FILE_WRITE, RiskLevel.HIGH, True),
            ("Edit", "Edit file with search/replace", ToolPermission.FILE_WRITE, RiskLevel.HIGH, True),
            ("Glob", "Find files by pattern", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
            ("Grep", "Search file contents with regex", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
        ].__iter__()
        return [
            ToolDefinition(
                name=n, description=d, parameters={},
                permission=p, risk_level=r, requires_approval=a,
            )
            for n, d, p, r, a in [
                ("Bash", "Execute shell commands", ToolPermission.SHELL_EXEC, RiskLevel.HIGH, True),
                ("Read", "Read file contents", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
                ("Write", "Write or create a file", ToolPermission.FILE_WRITE, RiskLevel.HIGH, True),
                ("Edit", "Edit file with search/replace", ToolPermission.FILE_WRITE, RiskLevel.HIGH, True),
                ("Glob", "Find files by pattern", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
                ("Grep", "Search file contents with regex", ToolPermission.FILE_READ, RiskLevel.SAFE, False),
            ]
        ]

    # ── Core: act() ──────────────────────────────────────────────

    async def act(
        self,
        context: ConversationContext,
        soul_profile: Any,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> ActionResult:
        if not self._available:
            return ActionResult(
                text="[Claude Code CLI 未安装。请先安装 Claude Code: https://docs.anthropic.com/en/docs/claude-code]",
                success=False,
                error_message="claude binary not found",
            )

        t_start = time.monotonic()

        try:
            # ── 1. Build Soul Profile (system prompt) ────────────
            system_prompt = ""
            if hasattr(soul_profile, 'build_system_prompt'):
                system_prompt = soul_profile.build_system_prompt(
                    context={
                        "channel_id": context.channel_id,
                        "participants": ", ".join(
                            f"{'Agent' if p.get('type') == 'agent' else 'User'}({p.get('id', '')[:8]})"
                            for p in (context.participants or [])
                        ),
                    },
                    memories=memory_context.episodic if memory_context else [],
                )

            # Add action-oriented instructions
            system_prompt += (
                "\n\n## Your Role"
                f"\nYou are an AI employee in an instant messaging platform. "
                f"Your name is {self._agent_name}. "
                "You are in a team channel. You have real tools to interact with the world. "
                "When asked to DO something, USE YOUR TOOLS — don't just describe what to do. "
                "Report your results clearly and concisely."
            )

            # ── 2. Build user message ────────────────────────────
            user_message = self._build_user_message(context)

            # ── 3. Build tool allowlist ──────────────────────────
            tool_permissions = self.config.get("tool_permissions", [])
            if isinstance(tool_permissions, str):
                tool_permissions = json.loads(tool_permissions) if tool_permissions else []
            allowed_tools = self._resolve_claude_tools(tool_permissions)

            # ── 4. Write temp files to avoid shell quoting issues ──
            #    Using files for both system prompt and user message.
            #    Pipe user message via stdin (type file.txt | claude -p -)
            import subprocess as _sp
            system_prompt_file = None
            prompt_file = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", prefix="maim_soul_",
                    delete=False, encoding="utf-8",
                ) as sf:
                    sf.write(system_prompt)
                    system_prompt_file = sf.name
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", prefix="maim_prompt_",
                    delete=False, encoding="utf-8",
                ) as pf:
                    pf.write(user_message)
                    prompt_file = pf.name
            except Exception:
                logger.warning("Failed to write temp files for Claude CLI")

            # Push thinking event
            if event_callback:
                await event_callback(AgentEvent(
                    agent_id=self._agent_id,
                    agent_name=self._agent_name,
                    event_type=AgentEventType.THINKING,
                    payload={"connector": "claude_code_cli", "model": self._model},
                ))

            # Build CLI flags (no prompt in args — piped via stdin)
            flags = [
                "--output-format", "json",
                "--model", self._model,
                "--max-turns", str(self._max_turns),
                "--permission-mode", self._permission_mode,
            ]
            if system_prompt_file:
                flags.extend(["--system-prompt-file", system_prompt_file])
            if allowed_tools:
                flags.extend(["--allowedTools", ",".join(allowed_tools)])

            # Pipe prompt from file: type prompt.txt | claude ... -p -
            flag_str = _sp.list2cmdline(flags)
            pipe_cmd = (
                f'type "{prompt_file}" | "{self._claude_bin}" {flag_str} -p -'
                if prompt_file
                else f'"{self._claude_bin}" {flag_str} -p "help"'
            )

            proc = await asyncio.create_subprocess_shell(
                pipe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace_dir,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=DEFAULT_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                proc.kill()
                self._cleanup_temp_files(system_prompt_file, prompt_file)
                return ActionResult(
                    text=f"[Claude Code 执行超时 ({DEFAULT_TIMEOUT_S}s)]",
                    success=False,
                    error_message="timeout",
                )
            finally:
                self._cleanup_temp_files(system_prompt_file, prompt_file)

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # ── 7. Parse Claude CLI JSON output ──────────────────
            if proc.returncode != 0 and not stdout.strip():
                error_msg = stderr[:500] or f"exit code {proc.returncode}"
                logger.error("Claude CLI error: %s", error_msg)
                return ActionResult(
                    text=f"[Claude Code 执行出错: {error_msg}]",
                    success=False,
                    error_message=error_msg,
                )

            try:
                # Claude CLI always outputs valid JSON on stdout when using --output-format json.
                # Find the JSON object (skip any BOM or leading garbage).
                clean = stdout.lstrip("﻿").strip()
                if clean and clean[0] != "{":
                    brace_idx = clean.find("{")
                    if brace_idx >= 0:
                        clean = clean[brace_idx:]
                    else:
                        raise json.JSONDecodeError("No JSON found", clean, 0)
                data = json.loads(clean)
            except (json.JSONDecodeError, UnicodeDecodeError) as je:
                logger.warning(
                    "Failed to parse Claude CLI JSON (len=%d, first 80 bytes: %r)",
                    len(stdout), stdout[:80] if isinstance(stdout, bytes) else stdout[:80],
                )
                # Fallback: try to extract useful text from whatever we got
                fallback_text = stdout[:2000] if stdout.strip() else "[Claude Code returned empty output]"
                return ActionResult(
                    text=fallback_text,
                    success=bool(stdout.strip()),
                    error_message=f"json_parse_error" if stdout.strip() else "empty_output",
                )

            # ── 7. Convert to ActionResult ───────────────────────
            result_text = data.get("result", "") or ""
            num_turns = data.get("num_turns", 0)
            cost_usd = data.get("total_cost_usd", 0)
            duration_ms = data.get("duration_ms", 0)
            is_error = data.get("is_error", False)
            stop_reason = data.get("stop_reason", "unknown")
            permission_denials = data.get("permission_denials", [])

            if is_error:
                api_error = data.get("api_error_status", "unknown")
                return ActionResult(
                    text=f"[Claude Code API 错误: {api_error}] {result_text[:500]}",
                    success=False,
                    error_message=str(api_error),
                )

            # Build tool executions from num_turns
            tool_executions = []
            if num_turns > 1:
                tool_executions = [{
                    "tool_name": "claude_code_cli",
                    "success": not is_error,
                    "summary": f"claude-cli: {num_turns} turns, {cost_usd:.4f} USD, {duration_ms}ms",
                    "duration_ms": duration_ms,
                }]

            memory_candidates = []
            if result_text and len(result_text) > 100:
                memory_candidates.append({
                    "type": "conversation_summary",
                    "content": result_text[:500],
                    "importance": 0.6,
                    "framework": "claude_code_cli",
                })

            total_ms = (time.monotonic() - t_start) * 1000

            # Push done event
            if event_callback:
                await event_callback(AgentEvent(
                    agent_id=self._agent_id,
                    agent_name=self._agent_name,
                    event_type=AgentEventType.AGENT_DONE,
                    payload={
                        "channel_id": context.channel_id,
                        "turns": num_turns,
                        "cost_usd": cost_usd,
                        "duration_ms": duration_ms,
                    },
                ))

            return ActionResult(
                text=result_text,
                tool_executions=tool_executions,
                reasoning_trace=f"claude_cli: turns={num_turns} cost=${cost_usd:.4f} stop={stop_reason}",
                memory_candidates=memory_candidates,
                total_duration_ms=total_ms,
                rounds=num_turns,
                success=True,
            )

        except Exception as e:
            logger.error("ClaudeCodeCLIConnector act() error: %s", e, exc_info=True)
            return ActionResult(
                text=f"[Claude Code 执行异常: {e}]",
                success=False,
                error_message=str(e),
            )

    # ── Core: act_stream() ───────────────────────────────────────

    async def act_stream(
        self,
        context: ConversationContext,
        soul_profile: Any,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        """Non-streaming — call act() and yield the full result."""
        result = await self.act(context, soul_profile, memory_context, event_callback)
        yield result.text

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _cleanup_temp_files(*paths: str | None) -> None:
        """Clean up temporary files."""
        for path in paths:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _build_user_message(self, context: ConversationContext) -> str:
        """Build the user prompt from conversation context."""
        parts: list[str] = []

        # Channel context
        if context.channel_id:
            parts.append(f"[Channel: #{context.channel_id}]")

        # Participants
        if context.participants:
            names = []
            for p in context.participants[:10]:
                pid = str(p.get("id", ""))[:8]
                ptype = p.get("type", "")
                name = p.get("name", "")
                tag = "AI" if ptype == "agent" else "User"
                if name:
                    names.append(f"{name}({tag})")
                else:
                    names.append(f"{tag}({pid})")
            if names:
                parts.append(f"Participants: {', '.join(names)}")

        # Messages
        for msg in context.messages[-20:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("sender_name", "")
            sender_type = msg.get("sender_type", "human")

            if role == "system":
                continue
            if not content.strip():
                continue

            if name and sender_type == "agent":
                parts.append(f"[{name} (AI)]: {content}")
            elif name:
                parts.append(f"{name}: {content}")
            else:
                parts.append(content)

        return "\n".join(parts)

    def _resolve_claude_tools(self, permissions: list[str]) -> list[str]:
        """Map Multi-agent-IM permissions to Claude Code CLI tool names."""
        if not permissions:
            return []

        perm_to_claude: dict[str, str] = {
            "file_read": "Read",
            "file_write": "Write",
            "file_delete": "Edit",    # Claude Code handles delete via Edit
            "shell_exec": "Bash",
            "git_read": "Bash",       # Git via Bash
            "git_write": "Bash",
            "search_code": "Grep",
            "file_search": "Glob",
        }

        tools: set[str] = set()
        for perm in permissions:
            mapped = perm_to_claude.get(perm)
            if mapped:
                tools.add(mapped)

        # Always allow Read (safe)
        if "file_read" in permissions and "Read" not in tools:
            tools.add("Read")

        return sorted(tools)
