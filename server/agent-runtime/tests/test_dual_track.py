"""
Phase 1 双轨运行集成测试。

验证:
  1. 旧 Agent（无 connector_type_v2）走 ReasoningEngine，功能不变
  2. 新 Agent（有 connector_type_v2 但 Connector 未注册）回退到旧路径
  3. ConnectorRouter 的路由决策正确性
  4. RoutingResult 序列化兼容 v1 API 格式
  5. SoulSerializer / MemoryService / EventBus 独立可用
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from agent_runtime.agent_service import AgentService
from connector_router import ConnectorRouter, RoutingResult, RouteDecision
from soul_serializer import SoulSerializer
from memory_service import MemoryService, MemoryContext
from event_bus import EventBus, AgentEvent, AgentEventType
from connector.base_v2 import (
    AgentConnectorV2,
    ActionResult,
    CapabilityInventory,
    AgentEventType as V2EventType,
    CONNECTOR_REGISTRY_V2,
    register_connector_v2,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def mock_db():
    """Mock Database with async methods."""
    db = MagicMock()
    db.create_agent = AsyncMock()
    db.get_agent = AsyncMock()
    db.list_agents = AsyncMock(return_value=[])
    db.update_agent_status = AsyncMock()
    db.get_memories = AsyncMock(return_value=[])
    db.get_all_memories = AsyncMock(return_value=[])
    db.save_memory = AsyncMock(return_value="mem_test_001")
    db.update_memory_tier = AsyncMock(return_value=True)
    db.delete_memory = AsyncMock(return_value=True)
    db.update_agent_connector = AsyncMock()
    return db


@pytest.fixture
def mock_reasoning_engine():
    """Mock ReasoningEngine (v1 fallback)."""
    engine = MagicMock()
    engine.process_message = AsyncMock()
    engine.process_wake = AsyncMock()
    engine.process_message_stream = MagicMock()
    return engine


@pytest.fixture
def old_agent_data():
    """旧 Agent — 无 connector_type_v2。"""
    return {
        "id": "agent_old_001",
        "name": "旧Agent",
        "role": "测试",
        "department": "QA",
        "status": "IDLE",
        "connector_type": "openai_compatible",
        "connector_type_v2": None,  # 未设置
        "connector_config": {"provider": "deepseek", "model": "deepseek-chat"},
        "identity": {"name": "旧Agent", "role": "测试"},
        "persona": {"openness": 0.5, "conscientiousness": 0.7},
        "value_system": {"core_principles": ["测试优先"]},
    }


@pytest.fixture
def new_agent_data():
    """新 Agent — 已设置 connector_type_v2（但 Connector 未注册）。"""
    return {
        "id": "agent_new_001",
        "name": "新Agent",
        "role": "研发",
        "department": "Engineering",
        "status": "IDLE",
        "connector_type": "claude_code",
        "connector_type_v2": "anthropic_agent",  # 已设置 v2 类型
        "connector_config": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "tool_permissions": ["send_message", "create_task", "file_read"],
        "identity": {"name": "新Agent", "role": "研发"},
        "persona": {"openness": 0.7, "conscientiousness": 0.8},
        "value_system": {"core_principles": ["代码质量优先"], "red_lines": ["不能删除生产数据"]},
    }


@pytest.fixture
def router(mock_db, mock_reasoning_engine):
    """ConnectorRouter with mocked dependencies."""
    return ConnectorRouter(db=mock_db, reasoning_engine=mock_reasoning_engine)


# ================================================================
# 路由决策测试
# ================================================================

class TestRouteDecision:
    """验证路由决策逻辑。"""

    def test_old_agent_routes_to_v1(self, router, old_agent_data):
        """旧 Agent（无 connector_type_v2）→ v1 路径。"""
        decision = router._decide_route(old_agent_data)
        assert decision.route == "v1:reasoning_engine"
        assert "not set" in decision.reason

    def test_new_agent_unregistered_falls_back(self, router, new_agent_data):
        """未注册的 v2 connector → v1 fallback。但如果是已注册的 connector → v2 path。"""
        # Phase 2: anthropic_agent IS now registered → routes to v2
        decision = router._decide_route(new_agent_data)
        assert decision.route in ("v2:anthropic_agent", "v1:fallback")
        # A truly unregistered type falls back
        unknown_agent = {**new_agent_data, "connector_type_v2": "nonexistent_framework_999"}
        decision2 = router._decide_route(unknown_agent)
        assert decision2.route == "v1:fallback"

    def test_legacy_connector_type_goes_v1(self, router):
        """connector_type_v2 为旧值 → v1 路径。"""
        agent = {"id": "legacy", "connector_type_v2": "openai_compatible"}
        decision = router._decide_route(agent)
        assert decision.route == "v1:reasoning_engine"

        agent["connector_type_v2"] = "claude_code"
        decision = router._decide_route(agent)
        assert decision.route == "v1:reasoning_engine"

    def test_empty_connector_type_goes_v1(self, router):
        """connector_type_v2 为空字符串 → v1 路径。"""
        decision = router._decide_route({"id": "empty", "connector_type_v2": ""})
        assert decision.route == "v1:reasoning_engine"

    def test_registered_connector_routes_to_v2(self, router, new_agent_data):
        """已注册的 v2 Connector → v2 路径。"""
        # Save original and register a test override
        _original = CONNECTOR_REGISTRY_V2.get("anthropic_agent")

        @register_connector_v2("anthropic_agent")
        class _TestConnector(AgentConnectorV2):
            def connector_name(self): return "test"
            def connector_version(self): return "0.1"
            async def initialize(self, c): pass
            async def health_check(self): return True
            async def shutdown(self): pass
            async def act(self, ctx, soul, mem, cb): return ActionResult()
            def capability_inventory(self): return CapabilityInventory()
            def tool_definitions(self): return []

        try:
            decision = router._decide_route(new_agent_data)
            assert decision.route == "v2:anthropic_agent"
        finally:
            # Restore original connector (don't just pop — that breaks other tests)
            if _original is not None:
                CONNECTOR_REGISTRY_V2["anthropic_agent"] = _original
            else:
                CONNECTOR_REGISTRY_V2.pop("anthropic_agent", None)


# ================================================================
# 路由执行测试
# ================================================================

class TestRouteExecution:
    """验证路由执行正确性。"""

    @pytest.mark.asyncio
    async def test_v1_route_uses_reasoning_engine(self, router, mock_db, mock_reasoning_engine, old_agent_data):
        """v1 路由 → 调用 ReasoningEngine.process_message()。"""
        mock_db.get_agent = AsyncMock(return_value=old_agent_data)
        mock_reasoning_engine.process_message = AsyncMock(return_value=MagicMock(
            text="v1 response", actions=[], reasoning_trace="v1", memory_saved=True,
        ))

        result = await router.route("agent_old_001", "ch_test", [{"role": "user", "content": "hi"}], [])

        assert mock_reasoning_engine.process_message.called
        assert result.text == "v1 response"
        assert result.memory_saved
        assert result.route_decision.route.startswith("v1:")

    @pytest.mark.asyncio
    async def test_v2_unregistered_falls_back_to_v1(self, router, mock_db, mock_reasoning_engine):
        """真正未注册的 v2 connector → 回退到 v1。"""
        mock_db.get_agent = AsyncMock(return_value={
            "id": "agent_unknown", "name": "Unknown", "role": "?",
            "connector_type": "claude_code", "connector_type_v2": "nonexistent_framework_999",
            "connector_config": {}, "tool_permissions": [],
            "identity": {"name": "X"}, "persona": {}, "value_system": {},
        })
        mock_reasoning_engine.process_message = AsyncMock(return_value=MagicMock(
            text="fallback response", actions=[], reasoning_trace="fallback", memory_saved=False,
        ))

        result = await router.route("agent_unknown", "ch_test", [{"role": "user", "content": "code"}], [])

        assert mock_reasoning_engine.process_message.called
        assert "fallback" in result.text
        assert result.route_decision.route == "v1:fallback"

    @pytest.mark.asyncio
    async def test_v2_anthropic_agent_routes_to_v2(self, router, mock_db):
        """anthropic_agent 已注册 → 路由决策指向 v2。"""
        mock_db.get_agent = AsyncMock(return_value={
            "id": "agent_anthro", "name": "AnthroAgent", "role": "Dev",
            "connector_type": "claude_code", "connector_type_v2": "anthropic_agent",
            "connector_config": {"model": "claude-sonnet-4-6"}, "tool_permissions": [],
            "identity": {"name": "A"}, "persona": {}, "value_system": {},
        })

        decision = router._decide_route(mock_db.get_agent.return_value)
        assert decision.route == "v2:anthropic_agent"

    @pytest.mark.asyncio
    async def test_wake_routes_to_v1(self, router, mock_db, mock_reasoning_engine, old_agent_data):
        """自主唤醒 → v1 路径。"""
        mock_db.get_agent = AsyncMock(return_value=old_agent_data)
        mock_reasoning_engine.process_wake = AsyncMock(return_value=MagicMock(
            text="wake message", memory_saved=True,
        ))

        result = await router.route_wake("agent_old_001", "ch_test", [])

        assert mock_reasoning_engine.process_wake.called
        assert result.text == "wake message"


# ================================================================
# RoutingResult 序列化
# ================================================================

class TestRoutingResultSerialization:
    """验证 RoutingResult → API JSON 兼容性。"""

    def test_basic_result(self):
        """基础字段序列化。"""
        result = RoutingResult(
            text="hello",
            actions=[],
            memory_saved=True,
            route_decision=RouteDecision(
                agent_id="a1", connector_type_v2="", route="v1:reasoning_engine", reason="not set"
            ),
        )

        # 模拟 _serialize_routing_result 的输出
        serialized = {
            "text": result.text,
            "actions": result.actions,
            "memory_saved": result.memory_saved,
            "_route": {
                "connector": result.route_decision.connector_type_v2 or "v1",
                "path": result.route_decision.route,
                "reason": result.route_decision.reason,
            },
        }

        assert serialized["text"] == "hello"
        assert serialized["memory_saved"] is True
        assert serialized["_route"]["path"] == "v1:reasoning_engine"

    def test_result_with_tool_executions(self):
        """含工具执行记录的序列化。"""
        result = RoutingResult(
            text="done",
            tool_executions=[
                {"tool_name": "read_file", "success": True, "summary": "OK", "duration_ms": 50},
            ],
            file_changes=[{"path": "/tmp/a.go", "operation": "modify"}],
            route_decision=RouteDecision(
                agent_id="a1", connector_type_v2="anthropic_agent", route="v2:anthropic_agent", reason="found"
            ),
        )

        assert len(result.tool_executions) == 1
        assert result.tool_executions[0]["tool_name"] == "read_file"
        assert result.route_decision.route == "v2:anthropic_agent"

    def test_result_backward_compat(self):
        """v1 clients 只关心 {text, actions, memory_saved} — 三个字段始终存在。"""
        result = RoutingResult(
            text="compat",
            actions=[{"type": "reply"}],
            memory_saved=False,
        )
        assert "text" in result.__dict__
        assert "actions" in result.__dict__
        assert "memory_saved" in result.__dict__


# ================================================================
# SoulSerializer 独立测试
# ================================================================

class TestSoulSerializer:
    """验证 SoulSerializer 独立可用（Phase 0 产出）。"""

    def test_build_from_agent_data(self):
        """从 agent_data dict 构建 SoulProfile。"""
        serializer = SoulSerializer()
        agent_data = make_agent_profile(id="test_1")
        soul = serializer.build_from_db(agent_data)
        assert soul.identity.name == "测试Agent"
        assert soul.persona.traits.conscientiousness == 0.9

    def test_serialize_to_anthropic(self):
        """序列化为 Anthropic system prompt。"""
        serializer = SoulSerializer()
        agent_data = make_agent_profile(id="test_1")
        soul = serializer.build_from_db(agent_data)
        result = serializer.serialize(soul, context={"channel_id": "ch1"}, memories=[])

        assert result.anthropic_system != ""
        assert "## Identity" in result.anthropic_system
        assert "测试Agent" in result.anthropic_system
        assert "## Action Capabilities" in result.anthropic_system  # v2 行动指令

    def test_serialize_to_openai(self):
        """序列化为 OpenAI system prompt。"""
        serializer = SoulSerializer()
        agent_data = make_agent_profile(id="test_1")
        soul = serializer.build_from_db(agent_data)
        result = serializer.serialize(soul, {}, [])
        assert result.openai_system != ""

    def test_serialize_to_hermes(self):
        """序列化为 Hermes profile dict。"""
        serializer = SoulSerializer()
        agent_data = make_agent_profile(id="test_1")
        soul = serializer.build_from_db(agent_data)
        result = serializer.serialize(soul, {}, [])
        assert result.hermes_profile is not None
        assert result.hermes_profile["identity"]["name"] == "测试Agent"


# ================================================================
# MemoryService 独立测试
# ================================================================

class TestMemoryService:
    """验证 MemoryService 独立可用。"""

    @pytest.mark.asyncio
    async def test_get_context_returns_memory_layers(self, mock_db):
        """检索返回分层记忆。"""
        mock_db.get_memories = AsyncMock(side_effect=[
            [{"content": {"knowledge": "core1"}, "tier": "core", "importance": 0.9}],  # core
            [{"content": {"knowledge": "work1"}, "tier": "working", "importance": 0.7}],  # working
            [],  # buffer
        ])

        svc = MemoryService(mock_db)
        ctx = await svc.get_context("agent_1")

        assert len(ctx.core_memories) > 0
        assert len(ctx.working_memories) > 0
        assert ctx.all_episodic(max_count=5)  # 可以合并

    @pytest.mark.asyncio
    async def test_save_conversation(self, mock_db):
        """保存对话 → 返回 memory_id。"""
        mock_db.save_memory = AsyncMock(return_value="mem_001")
        svc = MemoryService(mock_db)
        mem_id = await svc.save_conversation(
            "agent_1",
            [{"role": "user", "content": "决策：上线新功能"}],
            {"channel_id": "ch1", "has_human_review": True},
        )
        assert mem_id is not None


# ================================================================
# EventBus 独立测试
# ================================================================

class TestEventBus:
    """验证 EventBus 独立可用。"""

    @pytest.mark.asyncio
    async def test_publish_without_redis(self):
        """无 Redis 时返回 None（offline mode）。"""
        bus = EventBus(redis=None)
        # 不应抛异常
        await bus.started("agent_1", "TestAgent")
        await bus.thinking("agent_1", "TestAgent")
        await bus.done("agent_1", "TestAgent")

    @pytest.mark.asyncio
    async def test_event_serialization(self):
        """事件序列化为 JSON。"""
        event = AgentEvent(
            agent_id="a1",
            agent_name="Test",
            event_type=AgentEventType.THINKING,
            payload={"channel_id": "ch1"},
        )
        d = event.to_dict()
        assert d["agent_id"] == "a1"
        assert d["event"] == "thinking"
        assert "ts" in d


# ================================================================
# AgentService 路由辅助测试
# ================================================================

class TestAgentServiceRouting:
    """验证 AgentService 的路由辅助方法。"""

    def test_old_agent_not_v2(self, mock_db):
        """旧 Agent 不是 v2。"""
        svc = AgentService(mock_db)
        assert not svc.is_v2_agent({"connector_type_v2": None})
        assert not svc.is_v2_agent({"connector_type_v2": ""})
        assert not svc.is_v2_agent({"connector_type_v2": "openai_compatible"})
        assert not svc.is_v2_agent({"connector_type_v2": "claude_code"})

    def test_new_agent_is_v2(self, mock_db):
        """新 Agent 是 v2。"""
        svc = AgentService(mock_db)
        assert svc.is_v2_agent({"connector_type_v2": "anthropic_agent"})
        assert svc.is_v2_agent({"connector_type_v2": "hermes_agent"})

    @pytest.mark.asyncio
    async def test_get_route_target_v1(self, mock_db):
        """旧 Agent → route target 'v1'。"""
        mock_db.get_agent = AsyncMock(return_value={"connector_type_v2": None})
        svc = AgentService(mock_db)
        target = await svc.get_route_target("agent_1")
        assert target == "v1"

    @pytest.mark.asyncio
    async def test_get_route_target_v2(self, mock_db):
        """新 Agent → route target 'v2:anthropic_agent'。"""
        mock_db.get_agent = AsyncMock(return_value={"connector_type_v2": "anthropic_agent"})
        svc = AgentService(mock_db)
        target = await svc.get_route_target("agent_1")
        assert target == "v2:anthropic_agent"


# ================================================================
# Helpers (from conftest pattern, duplicated here for standalone)
# ================================================================

def make_agent_profile(**overrides) -> dict:
    """创建测试用 Agent 配置。"""
    defaults = {
        "name": "测试Agent",
        "role": "测试工程师",
        "department": "质量保障部",
        "id": "test_1",
        "persona": {
            "openness": 0.5,
            "conscientiousness": 0.9,
            "extraversion": 0.3,
            "agreeableness": 0.7,
            "neuroticism": 0.2,
            "communication": {"verbosity": 0.5, "formality": 0.5, "humor": 0.1, "directness": 0.7},
            "decision_making": {"risk_tolerance": 0.3, "data_driven": 0.8, "speed_accuracy": 0.4, "autonomy": 0.6},
        },
        "values": {
            "core_principles": ["质量优先"],
            "red_lines": ["不能修改生产数据库"],
        },
        "connector_type": "openai_compatible",
        "connector_type_v2": None,
        "connector_config": {},
        "tool_permissions": [],
        "sandbox_config": {},
    }
    defaults.update(overrides)
    return defaults
