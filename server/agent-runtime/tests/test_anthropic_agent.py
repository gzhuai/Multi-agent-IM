"""
Phase 2 AnthropicAgentConnector 测试。

验证:
  1. Connector 注册与接口合规
  2. 工具过滤（按权限白名单）
  3. Agent Loop 模拟（mock Anthropic API 响应）
  4. ActionResult 序列化
  5. 路径安全（path traversal 防护）
  6. 参数脱敏
  7. Memory candidates 提取
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from soul_engine.profile import SoulProfile, Identity, Persona, PersonaTraits, ValueSystem, CommunicationStyle, DecisionStyle
from connector.base import ConversationContext, MemorySnapshot
from connector.base_v2 import (
    AgentConnectorV2,
    ActionResult,
    AgentEvent,
    AgentEventType,
    CapabilityInventory,
    FileChange,
    ToolExecution,
    CONNECTOR_REGISTRY_V2,
    get_connector_v2,
    RiskLevel,
    ToolPermission,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def sample_soul_profile():
    """Standard test soul profile."""
    return SoulProfile(
        identity=Identity(name="TestAgent", display_name="Test", role="tester", department="QA"),
        persona=Persona(
            traits=PersonaTraits(openness=0.5, conscientiousness=0.7, extraversion=0.5, agreeableness=0.7, neuroticism=0.3),
            communication=CommunicationStyle(verbosity=0.5, formality=0.5, humor=0.1, directness=0.7),
            decision_making=DecisionStyle(risk_tolerance=0.3, data_driven=0.8, speed_accuracy=0.4, autonomy=0.5),
        ),
        values=ValueSystem(core_principles=["quality"], red_lines=["no prod db"]),
    )


@pytest.fixture
def sample_context():
    """Standard conversation context."""
    return ConversationContext(
        channel_id="ch_test",
        messages=[
            {"role": "user", "content": "Please fix the bug in main.go", "sender_name": "Dev1", "sender_type": "human"},
        ],
        participants=[
            {"id": "user_1", "type": "human", "name": "Dev1"},
        ],
        mentioned=True,
    )


@pytest.fixture
def sample_memory():
    """Empty memory snapshot."""
    return MemorySnapshot(episodic=[], semantic=[], relational=[])


@pytest.fixture
def connector():
    """Get AnthropicAgentConnector class from registry."""
    from connector.anthropic_agent import AnthropicAgentConnector
    return AnthropicAgentConnector()


# ================================================================
# Registration & Interface
# ================================================================

class TestConnectorRegistration:
    """Connector is properly registered in CONNECTOR_REGISTRY_V2."""

    def test_registered_in_registry(self):
        """After import, 'anthropic_agent' is in the registry."""
        # Import triggers @register_connector_v2
        from connector.anthropic_agent import AnthropicAgentConnector  # noqa
        assert "anthropic_agent" in CONNECTOR_REGISTRY_V2
        assert get_connector_v2("anthropic_agent") is AnthropicAgentConnector

    def test_connector_name_and_version(self, connector):
        assert connector.connector_name() == "anthropic_agent"
        assert connector.connector_version() == "2.0.0"


class TestInterfaceCompliance:
    """All required AgentConnectorV2 methods are implemented."""

    def test_implements_abstract_methods(self, connector):
        assert callable(connector.act)
        assert callable(connector.act_stream)
        assert callable(connector.capability_inventory)
        assert callable(connector.tool_definitions)
        assert callable(connector.initialize)
        assert callable(connector.health_check)
        assert callable(connector.shutdown)


# ================================================================
# Capability Inventory
# ================================================================

class TestCapabilityInventory:
    """Capability inventory accurately reflects connector abilities."""

    def test_inventory_structure(self, connector):
        inv = connector.capability_inventory()
        assert inv.framework == "anthropic_agent"
        assert inv.file_read is True
        assert inv.file_write is True
        assert inv.shell_execution is True
        assert inv.git_read is True
        assert inv.git_write is True
        assert inv.streaming is True
        assert inv.supports_prompt_caching is True
        assert inv.max_context_tokens == 200000

    def test_tool_definitions_count(self, connector):
        tools = connector.tool_definitions()
        assert len(tools) == 12  # exactly 12 tools

    def test_tool_definitions_have_metadata(self, connector):
        tools = connector.tool_definitions()
        for t in tools:
            assert t.name != ""
            assert t.description != ""
            assert t.permission is not None
            assert t.risk_level is not None

    def test_approval_required_tools(self, connector):
        policy = connector.approval_policy()
        # These tools should require approval
        assert policy.get("write_file") is True
        assert policy.get("shell_exec") is True
        assert policy.get("git_commit") is True
        # These should NOT
        assert policy.get("read_file") is False
        assert policy.get("list_files") is False
        assert policy.get("send_message") is False


# ================================================================
# Tool Filtering
# ================================================================

class TestToolFiltering:
    """Tools are filtered by permission set."""

    @pytest.mark.asyncio
    async def test_filtered_tools_respects_permissions(self, connector):
        """With limited permissions, only allowed tools are sent to API."""
        await connector.initialize({
            "agent_id": "test",
            "agent_name": "Test",
            "tool_permissions": ["send_message", "read_file"],
            "model": "claude-sonnet-4-6",
        })

        filtered = connector._filtered_tools({"send_message", "read_file"})
        names = {t["name"] for t in filtered}
        assert "send_message" in names
        assert "read_file" in names
        assert "write_file" not in names
        assert "shell_exec" not in names

    @pytest.mark.asyncio
    async def test_empty_permissions_returns_all(self, connector):
        """Empty permission set = all tools available."""
        await connector.initialize({
            "agent_id": "test",
            "agent_name": "Test",
            "tool_permissions": [],
            "model": "claude-sonnet-4-6",
        })
        filtered = connector._filtered_tools(set())
        assert len(filtered) == 12  # all tools


# ================================================================
# Agent Loop (Mock)
# ================================================================

class TestAgentLoop:
    """Agent loop with mock Anthropic API."""

    @pytest.mark.asyncio
    async def test_simple_text_response(self, connector, sample_soul_profile, sample_context, sample_memory):
        """When Anthropic returns text only (no tool_use), loop ends immediately."""
        await connector.initialize({
            "agent_id": "test",
            "agent_name": "Test",
            "tool_permissions": ["send_message", "read_file"],
            "model": "claude-sonnet-4-6",
        })

        txt_block = MagicMock()
        txt_block.type = "text"
        txt_block.text = "I analyzed the bug. It seems safe."

        mock_response = MagicMock()
        mock_response.content = [txt_block]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_response.stop_reason = "end_turn"
        connector._backend = "anthropic"
        connector._anthropic = MagicMock(messages=MagicMock(create=AsyncMock(return_value=mock_response)))

        result = await connector.act(sample_context, sample_soul_profile, sample_memory)

        assert result.text == "I analyzed the bug. It seems safe."
        assert result.success is True
        assert result.rounds == 1
        assert len(result.tool_executions) == 0

    @pytest.mark.asyncio
    async def test_tool_use_loop(self, connector, sample_soul_profile, sample_context, sample_memory):
        """When Anthropic returns tool_use blocks, they are executed and loop continues."""
        await connector.initialize({
            "agent_id": "test",
            "agent_name": "Test",
            "tool_permissions": ["send_message", "read_file", "shell_exec"],
            "model": "claude-sonnet-4-6",
        })

        mock_client = MagicMock()

        # Response 1: tool_use (read_file)
        txt_block_1 = MagicMock()
        txt_block_1.type = "text"
        txt_block_1.text = "Let me read the file first."
        tu_block_1 = MagicMock()
        tu_block_1.type = "tool_use"
        tu_block_1.name = "read_file"
        tu_block_1.id = "tool_001"
        tu_block_1.input = {"path": "main.go", "max_lines": 100}

        resp1 = MagicMock()
        resp1.content = [txt_block_1, tu_block_1]
        resp1.usage = MagicMock(input_tokens=200, output_tokens=80)
        resp1.stop_reason = "tool_use"

        # Response 2: final text (after tool_result)
        txt_block_2 = MagicMock()
        txt_block_2.type = "text"
        txt_block_2.text = "The bug is on line 42. Fixed."

        resp2 = MagicMock()
        resp2.content = [txt_block_2]
        resp2.usage = MagicMock(input_tokens=300, output_tokens=30)
        resp2.stop_reason = "end_turn"

        mock_client.messages.create = AsyncMock(side_effect=[resp1, resp2])
        connector._backend = "anthropic"
        connector._anthropic = mock_client

        # Patch read_file to return mock content
        original_handler = connector._tool_handlers["read_file"]
        connector._tool_handlers["read_file"] = AsyncMock(return_value={
            "success": True, "output": "package main\n\nfunc main() {}\n",
        })

        try:
            result = await connector.act(sample_context, sample_soul_profile, sample_memory)
        finally:
            connector._tool_handlers["read_file"] = original_handler

        assert result.text == "The bug is on line 42. Fixed."
        assert result.success is True
        assert result.rounds == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_name == "read_file"
        assert result.tool_executions[0].success is True

    @pytest.mark.asyncio
    async def test_max_rounds_guard(self, connector, sample_soul_profile, sample_context, sample_memory):
        """Agent loop stops at MAX_TOOL_ROUNDS (20) to prevent infinite loops."""
        await connector.initialize({
            "agent_id": "test",
            "agent_name": "Test",
            "tool_permissions": ["read_file"],
            "model": "claude-sonnet-4-6",
        })

        mock_client = MagicMock()
        # Always return tool_use (infinite loop simulation)
        tu_block = MagicMock()
        tu_block.type = "tool_use"
        tu_block.name = "read_file"
        tu_block.id = "tool_loop"
        tu_block.input = {"path": "file.txt"}

        resp = MagicMock()
        resp.content = [tu_block]
        resp.usage = MagicMock(input_tokens=100, output_tokens=20)
        resp.stop_reason = "tool_use"
        mock_client.messages.create = AsyncMock(return_value=resp)
        connector._backend = "anthropic"
        connector._anthropic = mock_client

        original_handler = connector._tool_handlers["read_file"]
        connector._tool_handlers["read_file"] = AsyncMock(return_value={
            "success": True, "output": "content",
        })
        try:
            result = await connector.act(sample_context, sample_soul_profile, sample_memory)
        finally:
            connector._tool_handlers["read_file"] = original_handler

        assert result.rounds <= 21  # MAX_TOOL_ROUNDS + 1 check
        # Should end with a graceful termination message
        assert result.text != ""
        assert len(result.tool_executions) == 20  # exactly MAX_TOOL_ROUNDS executions


# ================================================================
# ActionResult Serialization
# ================================================================

class TestActionResult:
    """ActionResult correctly captures all fields."""

    def test_basic_result(self):
        result = ActionResult(
            text="Done.",
            tool_executions=[],
            file_changes=[],
            success=True,
            rounds=3,
            tokens_used=500,
            total_duration_ms=2500.0,
        )
        assert result.text == "Done."
        assert result.success
        assert result.rounds == 3

    def test_result_with_file_changes(self):
        result = ActionResult(
            text="Fixed the bug.",
            file_changes=[
                FileChange(path="main.go", operation="modify", diff="-old\n+new"),
                FileChange(path="test/main_test.go", operation="create"),
            ],
            tool_executions=[
                ToolExecution(tool_name="write_file", tool_params={"path": "main.go"},
                             success=True, result_summary="OK", duration_ms=5.0),
            ],
        )
        assert len(result.file_changes) == 2
        assert result.file_changes[0].path == "main.go"
        assert result.file_changes[1].operation == "create"

    def test_error_result(self):
        result = ActionResult(
            text="抱歉，服务不可用。",
            success=False,
            error_message="API rate limit exceeded",
        )
        assert result.success is False
        assert result.error_message == "API rate limit exceeded"


# ================================================================
# Security Tests
# ================================================================

class TestSecurity:
    """Security: path traversal prevention and param sanitization."""

    def test_safe_path_prevents_traversal(self, connector):
        """Path traversal is rejected."""
        with pytest.raises(ValueError, match="traversal"):
            connector._safe_path("../../../etc/passwd")

    def test_safe_path_allows_normal(self, connector):
        """Normal paths are allowed."""
        result = connector._safe_path("src/main.go")
        assert "src" in result and "main.go" in result

    def test_safe_params_truncates_long_values(self, connector):
        """Long string values in params are truncated."""
        params = {
            "content": "x" * 5000,
            "path": "main.go",
            "api_key": "secret123",
        }
        safe = connector._safe_params(params)
        assert len(safe["content"]) <= 303  # 300 + "..."
        assert safe["api_key"] == "***"
        assert safe["path"] == "main.go"


# ================================================================
# Memory Candidates
# ================================================================

class TestMemoryCandidates:
    """Memory extraction from tool executions."""

    def test_extract_from_tool_executions(self, connector):
        executions = [
            ToolExecution(tool_name="read_file", tool_params={},
                         success=True, result_summary="Read main.go"),
            ToolExecution(tool_name="shell_exec", tool_params={"command": "go test"},
                         success=True, result_summary="Tests passed"),
        ]
        candidates = connector._extract_memory_candidates("", executions)
        assert len(candidates) >= 2
        assert any(c["tool"] == "read_file" for c in candidates)

    def test_extract_from_text(self, connector):
        # Even with no tool executions, long text can be a memory candidate (>100 chars)
        candidates = connector._extract_memory_candidates(
            "This is an important conversation about architecture decisions. "
            "The team decided to migrate from monolith to microservices because "
            "of scalability concerns and developer productivity issues.", [],
        )
        assert len(candidates) >= 1
        assert candidates[0]["type"] == "conversation_summary"


# ================================================================
# Tool Handler Tests (Unit)
# ================================================================

class TestToolHandlers:
    """Individual tool handlers behave correctly."""

    @pytest.mark.asyncio
    async def test_read_file_nonexistent(self, connector):
        result = await connector._handle_read_file(path="nonexistent_file_xyz.txt")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_files(self, connector):
        """List files from a relative path."""
        result = await connector._handle_list_files(directory=".", max_depth=1)
        # May succeed or fail gracefully depending on sandbox setup
        assert isinstance(result, dict)
        assert "success" in result
        if result["success"]:
            assert isinstance(result["output"], str)

    @pytest.mark.asyncio
    async def test_send_message(self, connector):
        result = await connector._handle_send_message(content="Hello world")
        assert result["success"] is True
        assert "Hello world" in result["output"]

    @pytest.mark.asyncio
    async def test_create_task(self, connector):
        result = await connector._handle_create_task(
            title="Fix login bug", description="The login returns 500",
            assignee_id="agent_1", priority="HIGH",
        )
        assert result["success"] is True
        assert result["output"].startswith("Task created:")
        assert result["task"]["priority"] == "HIGH"

    @pytest.mark.asyncio
    async def test_update_task(self, connector):
        result = await connector._handle_update_task(
            task_id="task-001", status="DONE", comment="Fixed and tested",
        )
        assert result["success"] is True
        assert "task-001" in result["output"]
        assert "DONE" in result["output"]
