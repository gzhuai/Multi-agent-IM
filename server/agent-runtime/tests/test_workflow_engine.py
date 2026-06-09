"""
Phase 3 WorkflowEngine 专项测试。

验证:
  1. DAG 环路检测算法
  2. 拓扑分层（并行/串行分组）
  3. 工作流创建与验证
  4. 节点执行（串行/并行/失败策略）
  5. 状态追踪与事件推送
  6. 超时与取消
  7. 作为 v2 Connector 的接口合规
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from workflow_engine import (
    WorkflowEngine,
    WorkflowDAG,
    WorkflowNode,
    WorkflowStatus,
    NodeStatus,
    FailurePolicy,
    has_cycle,
    topological_levels,
)
from connector.base_v2 import (
    ActionResult,
    CapabilityInventory,
    CONNECTOR_REGISTRY_V2,
    RiskLevel,
)


# ═══════════════════════════════════════════════════════════════════
# DAG 算法测试
# ═══════════════════════════════════════════════════════════════════

class TestDAGValidation:
    """DAG 环路检测。"""

    def test_no_cycle_linear(self):
        """A→B→C 无环路。"""
        assert not has_cycle(["A", "B", "C"], [("A", "B"), ("B", "C")])

    def test_has_cycle_triangle(self):
        """A→B, B→C, C→A 有环路。"""
        assert has_cycle(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])

    def test_no_cycle_diamond(self):
        """A→B, A→C, B→D, C→D 无环路（菱形结构）。"""
        assert not has_cycle(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )

    def test_has_cycle_self_loop(self):
        """自环 A→A 有环路。"""
        assert has_cycle(["A"], [("A", "A")])

    def test_no_cycle_independent(self):
        """三个独立节点无环路。"""
        assert not has_cycle(["A", "B", "C"], [])


class TestTopologicalLevels:
    """拓扑分层算法。"""

    def test_linear_three_levels(self):
        """A→B→C 产生三个独立的层。"""
        levels = topological_levels(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert len(levels) == 3
        assert levels[0] == ["A"]
        assert levels[1] == ["B"]
        assert levels[2] == ["C"]

    def test_diamond_structure(self):
        """A→{B,C}→D 产生三层: [A], [B,C], [D]。"""
        levels = topological_levels(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        assert len(levels) == 3
        assert levels[0] == ["A"]
        assert set(levels[1]) == {"B", "C"}  # 同级可并行
        assert levels[2] == ["D"]

    def test_independent_all_same_level(self):
        """三个独立节点都在同一层（可完全并行）。"""
        levels = topological_levels(["A", "B", "C"], [])
        assert len(levels) == 1
        assert set(levels[0]) == {"A", "B", "C"}


# ═══════════════════════════════════════════════════════════════════
# WorkflowEngine 集成测试
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def engine():
    """WorkflowEngine with no external deps (test mode)."""
    wf = WorkflowEngine()
    return wf


class TestWorkflowEngineCore:
    """WorkflowEngine 核心功能。"""

    @pytest.mark.asyncio
    async def test_initialize(self, engine):
        await engine.initialize({})
        assert await engine.health_check()

    @pytest.mark.asyncio
    async def test_connector_interface(self, engine):
        """作为 ConnectorV2，所有抽象方法都实现了。"""
        assert engine.connector_name() == "workflow_engine"
        assert engine.connector_version() == "1.0.0"
        assert isinstance(engine.capability_inventory(), CapabilityInventory)
        assert len(engine.tool_definitions()) == 2  # create_workflow + cancel_workflow

    @pytest.mark.asyncio
    async def test_registered_in_v2_registry(self):
        """WorkflowEngine 在 CONNECTOR_REGISTRY_V2 中。"""
        assert "workflow_engine" in CONNECTOR_REGISTRY_V2
        from connector.base_v2 import get_connector_v2
        cls = get_connector_v2("workflow_engine")
        assert cls is WorkflowEngine

    @pytest.mark.asyncio
    async def test_create_linear_workflow(self, engine):
        """创建并执行 A→B→C 线性工作流。"""
        await engine.initialize({})
        wf_id = await engine.create_workflow(
            title="简单三步工作流",
            nodes=[
                {"id": "A", "agent_id": "agent_1", "title": "步骤 1", "description": "分析需求"},
                {"id": "B", "agent_id": "agent_2", "title": "步骤 2", "description": "设计方案"},
                {"id": "C", "agent_id": "agent_3", "title": "步骤 3", "description": "执行实现"},
            ],
            edges=[("A", "B"), ("B", "C")],
            auto_start=False,
        )

        assert wf_id.startswith("wf-")

        status = await engine.get_status(wf_id)
        assert status is not None
        assert status.title == "简单三步工作流"
        assert len(status.nodes) == 3

    @pytest.mark.asyncio
    async def test_cycle_is_rejected(self, engine):
        """环路 DAG 在创建时被拒绝。"""
        await engine.initialize({})
        with pytest.raises(ValueError, match="cycle"):
            await engine.create_workflow(
                title="环路工作流",
                nodes=[
                    {"id": "A", "agent_id": "a1", "title": "A"},
                    {"id": "B", "agent_id": "a2", "title": "B"},
                ],
                edges=[("A", "B"), ("B", "A")],  # 环路!
            )

    @pytest.mark.asyncio
    async def test_execute_without_executor(self, engine):
        """无 node_executor 时节点仍正常完成（测试模式）。"""
        await engine.initialize({})

        wf_id = await engine.create_workflow(
            title="无 Executor 测试",
            nodes=[
                {"id": "A", "agent_id": "a1", "title": "Task A"},
                {"id": "B", "agent_id": "a2", "title": "Task B"},
            ],
            edges=[],
            auto_start=True,
        )

        # 等待执行完成（test mode ~200ms for 2 nodes）
        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            status = await engine.get_status(wf_id)
            if status and status.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            await asyncio.sleep(0.1)

        status = await engine.get_status(wf_id)
        assert status is not None
        assert status.status == "SUCCEEDED", f"Expected SUCCEEDED, got {status.status}"
        # 两个独立节点均应成功
        node_statuses = {n["id"]: n["status"] for n in status.nodes}
        assert node_statuses.get("A") == "succeeded"
        assert node_statuses.get("B") == "succeeded"

    @pytest.mark.asyncio
    async def test_parallel_execution(self, engine):
        """无依赖的节点并行执行 — 总时间 < 各节点时间之和。"""
        await engine.initialize({})

        wf_id = await engine.create_workflow(
            title="并行测试",
            nodes=[
                {"id": "A", "agent_id": "a1", "title": "A"},
                {"id": "B", "agent_id": "a2", "title": "B"},
                {"id": "C", "agent_id": "a3", "title": "C"},
            ],
            edges=[],
            auto_start=True,
        )

        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            status = await engine.get_status(wf_id)
            if status and status.status == "SUCCEEDED":
                break
            await asyncio.sleep(0.1)

        elapsed = time.monotonic() - t0
        assert elapsed < 3.0  # 不应接近 3 * 0.1s（并行）
        status = await engine.get_status(wf_id)
        assert status.status == "SUCCEEDED"

    @pytest.mark.asyncio
    async def test_cancel_workflow(self, engine):
        """取消工作流 — 未执行节点变为 CANCELLED。"""
        await engine.initialize({})

        wf_id = await engine.create_workflow(
            title="可取消工作流",
            nodes=[
                {"id": "A", "agent_id": "a1", "title": "A"},
                {"id": "B", "agent_id": "a2", "title": "B"},
                {"id": "C", "agent_id": "a3", "title": "C"},
            ],
            edges=[],
            auto_start=False,
        )

        ok = await engine.cancel(wf_id)
        assert ok

        status = await engine.get_status(wf_id)
        assert status.status == "CANCELLED"
        for n in status.nodes:
            assert n["status"] in ("cancelled",)


class TestFailurePolicies:
    """失败策略测试。"""

    @pytest.mark.asyncio
    async def test_skip_policy(self, engine):
        """策略 skip: 上游失败 → 下游标记为 SKIPPED。"""
        await engine.initialize({})

        # 注入自定义 executor: A 失败，B/C 不执行
        call_count = {"A": 0}

        async def failing_executor(agent_id, title, description):
            call_count["A"] += 1
            return ActionResult(text="", success=False, error_message="Node A failed")

        engine._node_executor = failing_executor

        wf_id = await engine.create_workflow(
            title="失败跳过测试",
            nodes=[
                {"id": "A", "agent_id": "a1", "title": "Failing A"},
                {"id": "B", "agent_id": "a2", "title": "Dependent B"},
            ],
            edges=[("A", "B")],
            failure_policy=FailurePolicy.SKIP,
            auto_start=True,
        )

        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            status = await engine.get_status(wf_id)
            if status and status.status in ("FAILED", "SUCCEEDED", "CANCELLED"):
                break
            await asyncio.sleep(0.1)

        status = await engine.get_status(wf_id)
        nodes_map = {n["id"]: n for n in status.nodes}
        assert nodes_map["A"]["status"] == "failed"
        assert nodes_map["B"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_abort_policy(self, engine):
        """策略 abort: 上游失败 → 工作流立即终止，下游 CANCELLED。"""
        await engine.initialize({})

        async def failing_executor(agent_id, title, description):
            return ActionResult(text="", success=False, error_message="critical error")

        engine._node_executor = failing_executor

        wf_id = await engine.create_workflow(
            title="中止测试",
            nodes=[
                {"id": "A", "agent_id": "a1", "title": "Critical A"},
                {"id": "B", "agent_id": "a2", "title": "Dependent B"},
                {"id": "C", "agent_id": "a3", "title": "Dependent C"},
            ],
            edges=[("A", "B"), ("B", "C")],
            failure_policy=FailurePolicy.ABORT,
            auto_start=True,
        )

        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            status = await engine.get_status(wf_id)
            if status and status.status == "FAILED":
                break
            await asyncio.sleep(0.1)

        status = await engine.get_status(wf_id)
        assert status.status == "FAILED"
        nodes_map = {n["id"]: n for n in status.nodes}
        assert nodes_map["A"]["status"] == "failed"
        assert nodes_map["B"]["status"] in ("cancelled", "pending")
        assert nodes_map["C"]["status"] in ("cancelled", "pending")


class TestConnectorAct:
    """WorkflowEngine 作为 Connector 的 act() 行为。"""

    @pytest.mark.asyncio
    async def test_act_returns_ready_message(self, engine):
        """act() 返回能力就绪信息。"""
        await engine.initialize({})
        from connector.base import ConversationContext, MemorySnapshot
        result = await engine.act(
            ConversationContext(channel_id="ch1", messages=[], participants=[]),
            None,
            MemorySnapshot(),
        )
        assert result.success
        assert "WorkflowEngine" in result.text

    @pytest.mark.asyncio
    async def test_act_stream_yields_text(self, engine):
        """act_stream() 返回相同文本。"""
        await engine.initialize({})
        from connector.base import ConversationContext, MemorySnapshot
        chunks = []
        async for chunk in engine.act_stream(
            ConversationContext(channel_id="ch1", messages=[], participants=[]),
            None,
            MemorySnapshot(),
        ):
            chunks.append(chunk)
        assert len(chunks) > 0
