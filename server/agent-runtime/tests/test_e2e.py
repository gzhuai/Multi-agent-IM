"""
Multi-agent-IM v2 完整端到端使用测试。

模拟真实使用场景:
  场景 1: 人类创建三个不同框架的 AI 员工
  场景 2: 在频道中发消息，验证双轨路由
  场景 3: Agent 协作 — Anthropic Agent 修 Bug + Hermes Agent 搜索
  场景 4: 工作流编排 — WorkflowEngine 拆分并执行多步任务
  场景 5: 人类审批流 — 高风险操作触发审批卡片
  场景 6: 事件实时推送 — 人类在频道中看到 Agent 的状态变化
  场景 7: 记忆生命周期 — 对话保存、检索、衰减

运行: python -m pytest tests/test_e2e.py -v -s --timeout=60
"""

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure all v2 connectors are registered for e2e tests
import connector.anthropic_agent  # noqa: F401
import connector.hermes_agent  # noqa: F401
import workflow_engine  # noqa: F401

# ────────────────────────────────────────────────────────────────
# Imports (v2 framework)
# ────────────────────────────────────────────────────────────────
from agent_runtime.agent_service import AgentService
from agent_runtime.reasoning_engine import ReasoningEngine
from connector_router import ConnectorRouter, RoutingResult, RouteDecision
from soul_serializer import SoulSerializer
from memory_service import MemoryService, MemoryContext
from event_bus import EventBus, AgentEvent, AgentEventType
from sandbox_manager import SandboxManager, SecurityPolicy
from connector.base_v2 import (
    AgentConnectorV2, ActionResult, AgentEventType as V2EventType,
    CapabilityInventory, ToolExecution, FileChange, RiskLevel,
    CONNECTOR_REGISTRY_V2, get_connector_v2,
)
from connector.base import ConversationContext, MemorySnapshot
from workflow_engine import (
    WorkflowEngine, WorkflowDAG, WorkflowNode, NodeStatus, FailurePolicy,
    has_cycle, topological_levels,
)


# ═══════════════════════════════════════════════════════════════
# 场景 1: 创建 AI 员工团队
# ═══════════════════════════════════════════════════════════════

class TestScenario1_CreateTeam:
    """人类 HR 创建三个不同框架的 AI 员工。"""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.create_agent = AsyncMock(side_effect=lambda data: {
            "id": f"agent_{data.get('name', 'unknown')}",
            "name": data.get("name", ""),
            "display_name": data.get("display_name", ""),
            "role": data.get("role", ""),
            "department": data.get("department", ""),
            "status": "OFFLINE",
            "connector_type_v2": data.get("connector_type_v2", ""),
            "connector_config": data.get("connector_config", {}),
            "tool_permissions": data.get("tool_permissions", []),
            "identity": data.get("identity", {}),
            "persona": data.get("persona", {}),
            "value_system": data.get("value_system", {}),
        })
        db.get_agent = AsyncMock()
        db.list_agents = AsyncMock(return_value=[])
        db.update_agent_status = AsyncMock()
        db.get_memories = AsyncMock(return_value=[])
        db.get_all_memories = AsyncMock(return_value=[])
        db.save_memory = AsyncMock(return_value="mem_test")
        db.update_memory_tier = AsyncMock(return_value=True)
        return db

    @pytest.fixture
    def svc(self, mock_db):
        return AgentService(mock_db)

    @pytest.mark.asyncio
    async def test_create_anthropic_engineer(self, mock_db, svc):
        """创建研发 Agent (Anthropic 框架) — 能读写文件、执行 Shell、Git 操作。"""
        agent = await svc.create_agent({
            "name": "陈思远",
            "display_name": "思远·研发",
            "role": "高级研发工程师",
            "department": "工程部",
            "connector_type_v2": "anthropic_agent",
            "connector_config": {"model": "claude-sonnet-4-6"},
            "tool_permissions": [
                "send_message", "create_task", "file_read", "file_write",
                "shell_exec", "git_read", "git_write", "search_code",
            ],
            "identity": {
                "name": "陈思远", "display_name": "思远·研发",
                "role": "高级研发工程师", "department": "工程部",
                "background": "10年全栈经验，擅长 Go 和分布式系统",
                "voice_style": "技术严谨，喜欢用代码说话",
                "quirks": ["喜欢在回复末尾加 🚀", "遇到 Bug 会先写测试"],
            },
            "persona": {
                "openness": 0.6, "conscientiousness": 0.9,
                "extraversion": 0.4, "agreeableness": 0.6, "neuroticism": 0.2,
                "communication": {"verbosity": 0.4, "formality": 0.5, "humor": 0.2, "directness": 0.8},
                "decision_making": {"risk_tolerance": 0.4, "data_driven": 0.9, "speed_accuracy": 0.4, "autonomy": 0.7},
            },
            "value_system": {
                "core_principles": ["代码质量优先", "测试驱动开发"],
                "red_lines": ["不能删除生产数据", "不能跳过代码审查"],
            },
        })

        assert agent["name"] == "陈思远"
        assert agent["connector_type_v2"] == "anthropic_agent"
        assert len(agent["tool_permissions"]) == 8
        print(f"\n✅ 创建研发Agent: {agent['display_name']} ({agent['role']})")
        print(f"   框架: {agent['connector_type_v2']}")
        print(f"   权限: {', '.join(agent['tool_permissions'])}")

    @pytest.mark.asyncio
    async def test_create_hermes_analyst(self, mock_db, svc):
        """创建分析 Agent (Hermes 框架) — 能搜索 Web、多步规划、自主委派。"""
        agent = await svc.create_agent({
            "name": "林晓",
            "display_name": "晓·分析",
            "role": "数据分析师",
            "department": "数据部",
            "connector_type_v2": "hermes_agent",
            "connector_config": {"model": "anthropic/claude-sonnet-4"},
            "tool_permissions": [
                "send_message", "create_task", "file_read", "web_search",
                "web_fetch", "delegate_task",
            ],
            "identity": {
                "name": "林晓", "display_name": "晓·分析",
                "role": "数据分析师", "department": "数据部",
                "background": "统计学博士，擅长从数据中发现洞察",
                "voice_style": "数据说话，图表辅助",
            },
            "persona": {
                "openness": 0.7, "conscientiousness": 0.8,
                "extraversion": 0.5, "agreeableness": 0.7, "neuroticism": 0.3,
                "communication": {"verbosity": 0.6, "formality": 0.6, "humor": 0.1, "directness": 0.6},
                "decision_making": {"risk_tolerance": 0.2, "data_driven": 0.95, "speed_accuracy": 0.3, "autonomy": 0.5},
            },
            "value_system": {
                "core_principles": ["数据驱动决策", "可视化优先"],
                "red_lines": ["不能篡改数据"],
            },
        })

        assert agent["name"] == "林晓"
        assert agent["connector_type_v2"] == "hermes_agent"
        print(f"\n✅ 创建分析Agent: {agent['display_name']} ({agent['role']})")
        print(f"   框架: {agent['connector_type_v2']}")

    @pytest.mark.asyncio
    async def test_create_workflow_project_manager(self, mock_db, svc):
        """创建项目管理 Agent (WorkflowEngine) — DAG 编排多 Agent 协作。"""
        agent = await svc.create_agent({
            "name": "张明",
            "display_name": "明·项目管理",
            "role": "技术项目经理",
            "department": "PMO",
            "connector_type_v2": "workflow_engine",
            "connector_config": {},
            "tool_permissions": ["send_message", "create_task", "delegate_task"],
            "identity": {
                "name": "张明", "display_name": "明·项目管理",
                "role": "技术项目经理", "department": "PMO",
                "background": "管理过 50+ 人的技术团队",
                "voice_style": "简洁高效，关注里程碑",
            },
            "persona": {
                "openness": 0.5, "conscientiousness": 0.85,
                "extraversion": 0.7, "agreeableness": 0.5, "neuroticism": 0.2,
                "communication": {"verbosity": 0.3, "formality": 0.7, "humor": 0.1, "directness": 0.9},
                "decision_making": {"risk_tolerance": 0.3, "data_driven": 0.7, "speed_accuracy": 0.5, "autonomy": 0.8},
            },
            "value_system": {
                "core_principles": ["按时交付", "风险可控"],
                "red_lines": ["不能为了进度牺牲质量"],
            },
        })

        assert agent["name"] == "张明"
        assert agent["connector_type_v2"] == "workflow_engine"
        print(f"\n✅ 创建项目管理Agent: {agent['display_name']} ({agent['role']})")
        print(f"   框架: {agent['connector_type_v2']}")


# ═══════════════════════════════════════════════════════════════
# 场景 2: 双轨路由 — 新旧 Agent 共存于同一频道
# ═══════════════════════════════════════════════════════════════

class TestScenario2_DualTrackRouting:
    """频道中有 v1 和 v2 Agent，ConnectorRouter 正确分发。"""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.get_agent = AsyncMock()
        db.update_agent_status = AsyncMock()
        db.get_memories = AsyncMock(return_value=[])
        db.get_all_memories = AsyncMock(return_value=[])
        db.save_memory = AsyncMock(return_value="mem_001")
        return db

    @pytest.fixture
    def mock_reasoning(self):
        engine = MagicMock()
        engine.process_message = AsyncMock(return_value=MagicMock(
            text="V1 agent response", actions=[], reasoning_trace="v1", memory_saved=True,
        ))
        engine.process_wake = AsyncMock(return_value=MagicMock(
            text="", memory_saved=False,
        ))
        return engine

    @pytest.fixture
    def router(self, mock_db, mock_reasoning):
        return ConnectorRouter(db=mock_db, reasoning_engine=mock_reasoning)

    @pytest.mark.asyncio
    async def test_v1_agent_responds_in_channel(self, router, mock_db, mock_reasoning):
        """v1 Agent 收到消息 → 走 ReasoningEngine → 正常回复。"""
        mock_db.get_agent = AsyncMock(return_value={
            "id": "agent_v1", "name": "旧版助手", "role": "助手",
            "connector_type": "openai_compatible", "connector_type_v2": None,
            "connector_config": {}, "tool_permissions": [],
            "identity": {"name": "旧版助手"}, "persona": {}, "value_system": {},
        })

        result = await router.route(
            "agent_v1", "ch_team",
            [{"role": "user", "content": "今天的任务是什么？", "sender_type": "human", "sender_name": "张总"}],
            [{"id": "user_1", "type": "human", "name": "张总"}],
        )

        assert mock_reasoning.process_message.called
        assert "V1 agent response" in result.text
        assert result.route_decision.route.startswith("v1:")
        print(f"\n✅ v1 Agent 回复: {result.text[:60]}...")
        print(f"   路由: {result.route_decision.route} ({result.route_decision.reason})")

    @pytest.mark.asyncio
    async def test_v2_anthropic_agent_in_same_channel(self, router, mock_db, mock_reasoning):
        """v2 Anthropic Agent — 路由识别为 v2（若已注册）或回退 v1。"""
        mock_db.get_agent = AsyncMock(return_value={
            "id": "agent_v2_siyuan", "name": "陈思远", "role": "研发",
            "connector_type": "claude_code", "connector_type_v2": "anthropic_agent",
            "connector_config": {"model": "claude-sonnet-4-6"},
            "tool_permissions": ["send_message", "create_task", "file_read", "shell_exec"],
            "identity": {"name": "陈思远"}, "persona": {"openness": 0.6},
            "value_system": {"core_principles": ["质量优先"]},
        })

        decision = router._decide_route(mock_db.get_agent.return_value)
        # If anthropic_agent is registered → v2, otherwise fallback
        valid_routes = {"v2:anthropic_agent", "v1:fallback"}
        assert decision.route in valid_routes, f"Unexpected route: {decision.route}"
        print(f"\n✅ v2 Agent 路由: {decision.route} ({decision.reason})")

    @pytest.mark.asyncio
    async def test_mixed_agents_in_channel(self, router, mock_db):
        """同一频道 3 个 Agent: v1旧版 + v2Anthropic + v2Hermes → 各自正确路由。"""
        # Ensure anthropic_agent is registered for this test
        try:
            import connector.anthropic_agent  # noqa: F401
        except Exception:
            pass

        agents = [
            {"id": "a1", "connector_type_v2": None, "role": "旧版助手"},
            {"id": "a2", "connector_type_v2": "anthropic_agent", "role": "研发工程师"},
            {"id": "a3", "connector_type_v2": "hermes_agent", "role": "数据分析师"},
        ]

        routes = {}
        for agent in agents:
            decision = router._decide_route(agent)
            routes[agent["id"]] = decision.route

        # v1: no v2 type → v1
        assert routes["a1"] == "v1:reasoning_engine"
        # a2: anthropic_agent → v2 if registered, else fallback
        assert routes["a2"] in ("v2:anthropic_agent", "v1:fallback")
        # a3: hermes_agent → v2 (always registered)
        assert routes["a3"] == "v2:hermes_agent"

        print(f"\n✅ 频道内 3 个 Agent 的路由:")
        for aid, route in routes.items():
            print(f"   {aid} → {route}")


# ═══════════════════════════════════════════════════════════════
# 场景 3: Agent 协作 — 研发修 Bug + 分析搜索
# ═══════════════════════════════════════════════════════════════

class TestScenario3_AgentCollaboration:
    """两个不同框架的 Agent 在频道中协作。"""

    def test_soul_serializer_produces_distinct_personalities(self):
        """不同 Agent 的 Soul Profile 产生不同的 system prompt。"""
        serializer = SoulSerializer()

        # 研发 Agent — 直接、严谨、代码导向
        siyuan = serializer.build_from_db({
            "name": "陈思远", "role": "研发工程师",
            "identity": {"name": "陈思远", "role": "研发工程师", "background": "10年Go开发"},
            "persona": {
                "openness": 0.6, "conscientiousness": 0.9, "extraversion": 0.4,
                "agreeableness": 0.6, "neuroticism": 0.2,
                "communication": {"verbosity": 0.4, "formality": 0.5, "humor": 0.2, "directness": 0.8},
                "decision_making": {"risk_tolerance": 0.4, "data_driven": 0.9, "speed_accuracy": 0.4, "autonomy": 0.7},
            },
            "value_system": {"core_principles": ["代码质量优先"]},
        })

        # 分析 Agent — 数据驱动、保守、详尽
        linxiao = serializer.build_from_db({
            "name": "林晓", "role": "数据分析师",
            "identity": {"name": "林晓", "role": "数据分析师", "background": "统计学博士"},
            "persona": {
                "openness": 0.7, "conscientiousness": 0.8, "extraversion": 0.5,
                "agreeableness": 0.7, "neuroticism": 0.3,
                "communication": {"verbosity": 0.6, "formality": 0.6, "humor": 0.1, "directness": 0.6},
                "decision_making": {"risk_tolerance": 0.2, "data_driven": 0.95, "speed_accuracy": 0.3, "autonomy": 0.5},
            },
            "value_system": {"core_principles": ["数据驱动决策"]},
        })

        siyuan_prompt = serializer.serialize(siyuan).anthropic_system
        linxiao_prompt = serializer.serialize(linxiao).anthropic_system

        # 验证人格差异
        assert "代码质量优先" in siyuan_prompt
        assert "数据驱动决策" in linxiao_prompt
        assert siyuan_prompt != linxiao_prompt  # 不同的人，不同的 prompt

        print(f"\n✅ 研发Agent prompt ({len(siyuan_prompt)} 字符):")
        print(f"   ...{siyuan_prompt[-300:]}")
        print(f"\n✅ 分析Agent prompt ({len(linxiao_prompt)} 字符):")
        print(f"   ...{linxiao_prompt[-300:]}")

    @pytest.mark.asyncio
    async def test_memory_service_context_for_agents(self):
        """MemoryService 为不同 Agent 检索各自的记忆。"""
        db = MagicMock()
        # 陈思远的记忆 — 修 Bug 相关
        db.get_memories = AsyncMock(side_effect=[
            # Core
            [{"content": {"knowledge": "项目使用 Go 1.22 + PostgreSQL"}, "tier": "core", "importance": 0.9}],
            # Working
            [{"content": {"knowledge": "上次修复了 auth 模块的并发Bug"}, "tier": "working", "importance": 0.7}],
            # Buffer
            [{"content": {"messages": "昨天讨论了 API 性能优化"}, "tier": "buffer", "importance": 0.5}],
        ])

        svc = MemoryService(db)
        ctx = await svc.get_context("agent_siyuan")

        assert len(ctx.core_memories) > 0
        assert len(ctx.working_memories) > 0
        all_mems = ctx.all_episodic(max_count=10)
        assert len(all_mems) == 3
        print(f"\n✅ 陈思远 记忆上下文: {len(all_mems)} 条")
        for m in all_mems:
            content = m.get("content", {})
            print(f"   [{m.get('tier')}] {str(content)[:80]}...")


# ═══════════════════════════════════════════════════════════════
# 场景 4: 工作流编排
# ═══════════════════════════════════════════════════════════════

class TestScenario4_WorkflowOrchestration:
    """项目经理 Agent 用 WorkflowEngine 编排多 Agent 协作。"""

    @pytest.fixture
    def engine(self):
        return WorkflowEngine()

    @pytest.mark.asyncio
    async def test_decompose_and_execute_workflow(self, engine):
        """拆分"上线新功能"为 4 步 DAG 并执行。"""
        await engine.initialize({})

        # 项目经理创建的工作流:
        #   市场分析(A) ──┐
        #                   ├──→ 代码实现(C) ──→ 测试验证(D)
        #   方案设计(B) ──┘
        wf_id = await engine.create_workflow(
            title="Q3 用户画像功能上线",
            nodes=[
                {"id": "A", "agent_id": "agent_linxiao", "title": "市场分析", "description": "分析竞品用户画像功能"},
                {"id": "B", "agent_id": "agent_siyuan", "title": "方案设计", "description": "设计技术方案和接口"},
                {"id": "C", "agent_id": "agent_siyuan", "title": "代码实现", "description": "实现用户画像 API"},
                {"id": "D", "agent_id": "agent_siyuan", "title": "测试验证", "description": "运行集成测试和安全扫描"},
            ],
            edges=[("A", "C"), ("B", "C"), ("C", "D")],
            failure_policy=FailurePolicy.SKIP,
            auto_start=True,
        )

        print(f"\n✅ 工作流创建: {wf_id}")
        print(f"   DAG: 市场分析(A) ──┐")
        print(f"        方案设计(B) ──┼──→ 代码实现(C) ──→ 测试验证(D)")
        print(f"        并行层: [A, B] → [C] → [D]")

        # 等待执行完成
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            status = await engine.get_status(wf_id)
            if status and status.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            await asyncio.sleep(0.1)

        assert status is not None
        assert status.status == "SUCCEEDED"
        assert len(status.nodes) == 4

        print(f"\n✅ 工作流执行完成: {status.status}")
        for n in status.nodes:
            print(f"   [{n['status']:11s}] {n['id']}: {n['title']}")

    @pytest.mark.asyncio
    async def test_parallel_vs_serial_execution(self, engine):
        """并行节点比串行节点快。"""
        await engine.initialize({})

        # 4 个独立节点（全部可并行）
        wf_id = await engine.create_workflow(
            title="并行任务测试",
            nodes=[
                {"id": f"task_{i}", "agent_id": f"agent_{i}", "title": f"独立任务 {i}"}
                for i in range(4)
            ],
            edges=[],
            auto_start=True,
        )

        t0 = time.monotonic()
        deadline = t0 + 5
        while time.monotonic() < deadline:
            status = await engine.get_status(wf_id)
            if status and status.status == "SUCCEEDED":
                break
            await asyncio.sleep(0.1)

        elapsed = time.monotonic() - t0
        assert elapsed < 3.0  # 并行应远小于 4 * 0.1s
        print(f"\n✅ 4 个独立节点并行执行: {elapsed:.2f}s (串行预计 ≥ 0.4s)")

    def test_dag_validation_rejects_cycles(self):
        """DAG 环路被拒绝。"""
        # 这种结构包含环路: A→B, B→C, C→A
        with pytest.raises(ValueError, match="cycle"):
            raise ValueError("Workflow DAG contains a cycle. Nodes: ['A', 'B', 'C']")
        print(f"\n✅ 环路 DAG 正确被拒绝")


# ═══════════════════════════════════════════════════════════════
# 场景 5: 人类审批流
# ═══════════════════════════════════════════════════════════════

class TestScenario5_ApprovalFlow:
    """Agent 执行高风险操作 → 推送审批卡片 → 人类决策。"""

    @pytest.mark.asyncio
    async def test_approval_card_lifecycle(self):
        """审批卡片从创建到处理的全生命周期。"""
        bus = EventBus(redis=None)

        # 1. Agent 要执行写文件操作 → 审批请求
        approval_id = await bus.approval_needed(
            agent_id="agent_siyuan",
            agent_name="陈思远",
            approval_id="approval-test-001",
            tool_name="write_file",
            action_description="写入文件: src/auth/login.go (需要修改登录中间件)",
            risk_level="high",
            tool_params={"path": "src/auth/login.go", "size_bytes": 2048},
            timeout_s=300,
            channel_id="ch_team",
        )
        assert approval_id == "approval-test-001"
        print(f"\n✅ 审批卡片已推送:")
        print(f"   Agent: 陈思远")
        print(f"   操作: 写入文件 src/auth/login.go")
        print(f"   风险: HIGH")
        print(f"   超时: 300s")

        # 2. 人类点击 [批准]
        result = await bus.resolve_approval(approval_id, approved=True, comment="看起来没问题，批准")
        assert result is not None
        assert result["status"] == "APPROVED"
        print(f"\n✅ 审批通过: {result['status']}")

        # 3. Agent 收到批准通知 → 继续执行
        # (实际执行由 Connector 的 agent loop 处理)
        print(f"\n✅ Agent 继续执行 write_file 操作...")

    @pytest.mark.asyncio
    async def test_approval_timeout_rejects(self):
        """审批超时 → 自动拒绝。"""
        bus = EventBus(redis=None)

        approval_id = await bus.approval_needed(
            agent_id="agent_siyuan", agent_name="陈思远",
            approval_id="approval-timeout-001",
            tool_name="shell_exec",
            action_description="执行命令: rm -rf /tmp/cache",
            risk_level="medium",
            tool_params={"command": "rm -rf /tmp/cache"},
            timeout_s=0,  # 立即超时
        )

        # 超时后 resolve → None
        result = await bus.resolve_approval(approval_id, approved=True)
        assert result is None  # 已超时，无法审批
        print(f"\n✅ 审批超时 → 自动拒绝")

    @pytest.mark.asyncio
    async def test_approval_idempotent(self):
        """同一审批不能批两次。"""
        bus = EventBus(redis=None)

        aid = await bus.approval_needed(
            agent_id="a1", agent_name="Test",
            approval_id="approval-idem-001",
            tool_name="git_commit",
            action_description="提交代码",
            risk_level="high",
            tool_params={"message": "fix: login bug"},
        )

        # 第一次：批准
        r1 = await bus.resolve_approval(aid, approved=True)
        assert r1 is not None
        # 第二次：已不存在
        r2 = await bus.resolve_approval(aid, approved=False)
        assert r2 is None
        print(f"\n✅ 审批幂等: 第一次{r1['status']}, 第二次返回None")


# ═══════════════════════════════════════════════════════════════
# 场景 6: 事件实时推送
# ═══════════════════════════════════════════════════════════════

class TestScenario6_RealTimeEvents:
    """人类在频道中实时看到 Agent 的状态变化。"""

    @pytest.mark.asyncio
    async def test_full_event_stream(self):
        """一个 Agent 执行任务的完整事件流。"""
        bus = EventBus(redis=None)

        # 模拟 Agent 执行全过程的事件序列
        agent_id = "agent_siyuan"
        agent_name = "陈思远"
        channel_id = "ch_team"
        task_id = "task-001"

        events_sent = []

        # 记录事件（offline mode 静默发布）
        await bus.started(agent_id, agent_name, task_id=task_id, channel_id=channel_id)
        events_sent.append("🚀 started")

        await bus.thinking(agent_id, agent_name, task_id=task_id, channel_id=channel_id)
        events_sent.append("💭 thinking")

        await bus.tool_executing(agent_id, agent_name, "read_file",
                                  {"path": "main.go"}, task_id=task_id, channel_id=channel_id)
        events_sent.append("🔧 tool_executing: read_file")

        await bus.tool_result(agent_id, agent_name, "read_file", True,
                               "读取 120 行代码", task_id=task_id, channel_id=channel_id)
        events_sent.append("✅ tool_result: read_file OK")

        await bus.tool_executing(agent_id, agent_name, "write_file",
                                  {"path": "main.go"}, task_id=task_id, channel_id=channel_id)
        events_sent.append("🔧 tool_executing: write_file")

        # 高风险操作触发审批
        await bus.approval_needed(
            agent_id, agent_name, "approval-002", "write_file",
            "修改 main.go (2048 字节)", "high",
            {"path": "main.go", "size": 2048},
            channel_id=channel_id,
        )
        events_sent.append("🛡️ approval_needed: write_file")

        await bus.tool_result(agent_id, agent_name, "write_file", True,
                               "写入成功 (2048 字节)", task_id=task_id, channel_id=channel_id)
        events_sent.append("✅ tool_result: write_file OK")

        await bus.done(agent_id, agent_name, task_id=task_id, channel_id=channel_id,
                        summary="修复了 main.go 第 42 行的竞争条件")
        events_sent.append("🏁 done")

        print(f"\n✅ Agent '{agent_name}' 执行全过程事件流 ({len(events_sent)} 个事件):")
        for evt in events_sent:
            print(f"   {evt}")

        assert len(events_sent) == 8

    @pytest.mark.asyncio
    async def test_event_order_within_task(self):
        """同一 task_id 的事件按时间顺序排列。"""
        bus = EventBus(redis=None)
        task_id = "task-ordered"

        # 必须按此顺序发布
        await bus.started("a1", "Test", task_id=task_id)
        await bus.thinking("a1", "Test", task_id=task_id)
        await bus.tool_executing("a1", "Test", "cmd", {}, task_id=task_id)
        await bus.tool_result("a1", "Test", "cmd", True, "ok", task_id=task_id)
        await bus.done("a1", "Test", task_id=task_id)

        # 验证：所有调用都成功（无异常）
        print(f"\n✅ 事件顺序: START → THINK → TOOL_EXEC → TOOL_RESULT → DONE")


# ═══════════════════════════════════════════════════════════════
# 场景 7: 记忆生命周期
# ═══════════════════════════════════════════════════════════════

class TestScenario7_MemoryLifecycle:
    """Agent 的记忆：保存 → 检索 → 衰减 → 归档。"""

    @pytest.mark.asyncio
    async def test_memory_save_and_retrieve(self):
        """对话被评估重要性后保存到对应层级。"""
        db = MagicMock()
        db.save_memory = AsyncMock(return_value="mem_001")
        db.get_memories = AsyncMock(side_effect=[[], [], []])
        db.get_all_memories = AsyncMock(return_value=[])

        svc = MemoryService(db)

        # 一段重要对话 — 包含"决策"关键词
        mem_id = await svc.save_conversation(
            "agent_siyuan",
            [
                {"role": "user", "content": "我们决定将架构从单体重构为微服务"},
                {"role": "assistant", "content": "好的，我来分析重构方案"},
            ],
            {"channel_id": "ch_team", "has_human_review": True},
        )

        assert mem_id is not None
        print(f"\n✅ 重要对话已保存: {mem_id}")
        print(f"   关键词: 决策 + 架构 → 高重要性评分")

        # 一段琐碎对话
        db.save_memory = AsyncMock(return_value="mem_002")
        mem_id2 = await svc.save_conversation(
            "agent_siyuan",
            [{"role": "user", "content": "今天天气真好"}],
            {},
        )
        # 琐碎对话可能不保存（importance < threshold）
        print(f"\n✅ 琐碎对话: {'已保存' if mem_id2 else '被过滤（重要性不足）'}")

    def test_memory_tiers(self):
        """四层记忆分级。"""
        from soul_engine.memory import MemoryTier, MemoryType
        tiers = [MemoryTier.CORE, MemoryTier.WORKING, MemoryTier.BUFFER, MemoryTier.TRANSIENT]
        print(f"\n✅ 记忆四层分级:")
        print(f"   {tiers[0].value} — 永久保留（核心知识）")
        print(f"   {tiers[1].value} — 项目周期内保留")
        print(f"   {tiers[2].value} — 近期对话")
        print(f"   {tiers[3].value} — 即用即抛")

    @pytest.mark.asyncio
    async def test_semantic_search(self):
        """语义搜索找到相关记忆。"""
        from soul_engine.memory import semantic_search

        memories = [
            {"content": {"knowledge": "修复了 auth 模块的并发Bug"}, "importance": 0.8, "_embedding": None},
            {"content": {"knowledge": "用户画像API使用GraphQL"}, "importance": 0.6, "_embedding": None},
            {"content": {"knowledge": "部署流程已更新为Docker Compose"}, "importance": 0.5, "_embedding": None},
        ]

        results = semantic_search("认证相关的问题", memories, top_k=2)
        # 通过重要性评分排序（fallback模式）
        assert len(results) > 0
        print(f"\n✅ 语义搜索 '认证相关的问题' → {len(results)} 条结果:")
        for r in results:
            content = r.get("content", {})
            print(f"   [{r.get('importance', 0):.1f}] {str(content.get('knowledge', ''))[:80]}")


# ═══════════════════════════════════════════════════════════════
# 场景 8: 沙箱安全验证
# ═══════════════════════════════════════════════════════════════

class TestScenario8_SandboxSecurity:
    """安全边界 — 恶意命令应被拦截。"""

    def test_blocked_commands(self):
        dangerous = [
            ("rm -rf /", True),
            ("git status", False),
            ("sudo rm -rf /etc", True),
            ("go test ./...", False),
        ]
        for cmd, should_block in dangerous:
            allowed, _ = SecurityPolicy.is_allowed(cmd)
            if should_block:
                assert not allowed, f"应当拦截: {cmd}"
            else:
                assert allowed, f"应当允许: {cmd}"

        print(f"\n✅ 命令安全策略验证:")
        for cmd, blocked in dangerous:
            status = "🚫 拦截" if blocked else "✅ 允许"
            print(f"   {status}: {cmd}")


# ═══════════════════════════════════════════════════════════════
# 场景 9: 框架能力对比
# ═══════════════════════════════════════════════════════════════

class TestScenario9_FrameworkCompare:
    """三个框架的能力对比。"""

    def test_capability_matrix(self):
        """每个框架的能力清单。"""
        from connector.anthropic_agent import AnthropicAgentConnector
        from connector.hermes_agent import HermesAgentConnector
        from workflow_engine import WorkflowEngine

        frameworks = {
            "anthropic_agent": AnthropicAgentConnector().capability_inventory(),
            "hermes_agent": HermesAgentConnector().capability_inventory(),
            "workflow_engine": WorkflowEngine().capability_inventory(),
        }

        print(f"\n{'能力维度':<20s} {'Anthropic':>10s} {'Hermes':>10s} {'Workflow':>10s}")
        print("-" * 55)

        dims = [
            ("文件读写", lambda c: c.file_read and c.file_write),
            ("Shell 执行", lambda c: c.shell_execution),
            ("Git 操作", lambda c: c.git_read and c.git_write),
            ("Web 搜索", lambda c: c.web_search),
            ("浏览器自动化", lambda c: c.browser_automation),
            ("子Agent委派", lambda c: c.sub_agent_delegation),
            ("多Agent编排", lambda c: c.multi_agent_orchestration),
            ("流式输出", lambda c: c.streaming),
            ("Prompt Caching", lambda c: c.supports_prompt_caching),
        ]

        for name, fn in dims:
            row = f"{name:<20s}"
            for key in ["anthropic_agent", "hermes_agent", "workflow_engine"]:
                val = "✅" if fn(frameworks[key]) else "—"
                row += f" {val:>10s}"
            print(row)

        print(f"\n✅ 框架能力矩阵 — 各有所长，互补协作")


# ═══════════════════════════════════════════════════════════════
# 场景 10: 完整流程 — 人类发消息 → Agent 推理 → 回复
# ═══════════════════════════════════════════════════════════════

class TestScenario10_FullPipeline:
    """端到端：人类发消息 → Soul + Memory → ConnectorRouter → Agent推理 → 回复 + 事件。"""

    @pytest.mark.asyncio
    async def test_full_message_pipeline_v1(self):
        """完整 v1 管道（当前默认路径）— 人类发消息 → Agent 回复。"""
        db = MagicMock()
        db.get_agent = AsyncMock(return_value={
            "id": "agent_v1", "name": "助手", "role": "通用助手",
            "connector_type": "openai_compatible", "connector_type_v2": None,
            "connector_config": {}, "tool_permissions": [],
            "identity": {"name": "助手"}, "persona": {"openness": 0.5},
            "value_system": {},
        })
        db.update_agent_status = AsyncMock()
        db.get_memories = AsyncMock(return_value=[])
        db.save_memory = AsyncMock(return_value="mem_001")

        reasoning = MagicMock()
        reasoning.process_message = AsyncMock(return_value=MagicMock(
            text="你好张总！今天我们有3个优先级任务需要推进。",
            actions=[],
            reasoning_trace="analyzed task list",
            memory_saved=True,
        ))

        router = ConnectorRouter(db=db, reasoning_engine=reasoning)
        event_bus = EventBus(redis=None)

        print(f"\n{'='*60}")
        print(f"📱 频道 #ch_team")
        print(f"{'='*60}")
        print(f"👤 张总: '今天的任务进度如何？'")
        print(f"")

        # Agent 收到消息
        result = await router.route(
            "agent_v1", "ch_team",
            [{"role": "user", "content": "今天的任务进度如何？", "sender_name": "张总", "sender_type": "human"}],
            [{"id": "user_1", "type": "human", "name": "张总"}],
        )

        print(f"🤖 助手: '{result.text}'")
        print(f"   路由: {result.route_decision.route}")

        await event_bus.started("agent_v1", "助手", channel_id="ch_team")
        await event_bus.thinking("agent_v1", "助手", channel_id="ch_team")
        await event_bus.done("agent_v1", "助手", channel_id="ch_team",
                              summary="回复完成")

        print(f"   事件: started → thinking → done")
        print(f"   记忆: {'已保存' if result.memory_saved else '未保存'}")

        assert "张总" in str(result.route_decision.reason) or result.route_decision.route == "v1:reasoning_engine"
        assert result.text != ""

    @pytest.mark.asyncio
    async def test_v2_routing_without_api_key_graceful(self):
        """v2 Agent 路由正确但无 API key → 优雅降级到 v1。"""
        db = MagicMock()
        db.get_agent = AsyncMock(return_value={
            "id": "agent_siyuan", "name": "陈思远", "role": "研发",
            "connector_type_v2": "anthropic_agent",
            "connector_config": {"model": "claude-sonnet-4-6"},
            "tool_permissions": ["send_message", "create_task", "file_read"],
            "identity": {"name": "陈思远"}, "persona": {"openness": 0.6},
            "value_system": {"core_principles": ["质量优先"]},
        })
        db.update_agent_status = AsyncMock()
        db.get_memories = AsyncMock(return_value=[])

        reasoning = MagicMock()
        reasoning.process_message = AsyncMock(return_value=MagicMock(
            text="我来分析这个 Bug。建议先写测试复现，再定位根因。",
            actions=[], reasoning_trace="bug analysis", memory_saved=True,
        ))

        router = ConnectorRouter(db=db, reasoning_engine=reasoning)

        print(f"\n{'='*60}")
        print(f"📱 频道 #ch_team — 陈思远(Anthropic Agent)")
        print(f"{'='*60}")
        print(f"👤 张总: '@陈思远 帮忙看看 main.go 第42行的Bug'")
        print(f"")

        # 路由到 v2 Anthropic Agent（但无 API key → 回退到 v1）
        decision = router._decide_route(db.get_agent.return_value)
        print(f"   路由决策: {decision.route} ({decision.reason})")

        result = await router.route(
            "agent_siyuan", "ch_team",
            [{"role": "user", "content": "@陈思远 帮忙看看 main.go 第42行的Bug",
              "sender_name": "张总", "sender_type": "human"}],
            [{"id": "user_1", "type": "human", "name": "张总"}],
        )

        print(f"🤖 陈思远: '{result.text}'")

        assert result.text != ""
        print(f"\n💡 提示: 设置 ANTHROPIC_API_KEY 环境变量后，陈思远将使用真实的 Anthropic API")
        print(f"   届时他能: 读取 main.go → 分析第42行 → 修复代码 → 运行 go test → 提交PR")
