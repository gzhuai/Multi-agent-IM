"""
WorkflowEngine — 轻量 DAG 编排引擎 (Phase 3)。

替代原计划的 OpenClaw Connector。OpenClaw 是竞品 AI 网关平台（Node.js），
不适合作为嵌入式的"大脑框架"。WorkflowEngine 在 Agent Runtime 内部提供
多 Agent 任务编排能力。

核心功能:
  1. DAG 定义与验证（环路检测）
  2. 节点并行/串行执行（无依赖 → 并行, 有依赖 → 串行）
  3. 失败策略（skip / continue / abort）
  4. 状态追踪与 EventBus 推送
  5. 超时控制
  6. 作为 v2 Connector 注册到 CONNECTOR_REGISTRY_V2

使用方式:
  engine = WorkflowEngine(db, event_bus, connector_router)
  wf_id = await engine.create(dag)
  status = await engine.get_status(wf_id)
  await engine.cancel(wf_id)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

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

# ═══════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════


class NodeStatus(str, Enum):
    PENDING = "pending"       # 等待上游完成（或等待执行）
    RUNNING = "running"       # 正在执行
    SUCCEEDED = "succeeded"   # 执行成功
    FAILED = "failed"         # 执行失败
    SKIPPED = "skipped"       # 上游失败，策略 skip
    CANCELLED = "cancelled"   # 被取消（超时或手动取消）


class FailurePolicy(str, Enum):
    SKIP = "skip"           # 跳过失败节点的下游
    CONTINUE = "continue"   # 下游继续执行（上游错误作为上下文）
    ABORT = "abort"         # 取消所有下游节点


@dataclass
class WorkflowNode:
    """工作流中的一个节点。"""
    id: str                              # 节点唯一 ID
    agent_id: str                        # 执行此节点的 Agent
    title: str                           # 任务标题
    description: str = ""                # 任务描述
    status: NodeStatus = NodeStatus.PENDING
    result: ActionResult | None = None   # 执行结果
    started_at: float = 0               # epoch seconds
    ended_at: float = 0                 # epoch seconds
    error_message: str = ""
    retries: int = 0                     # 已重试次数
    max_retries: int = 1                 # 最大重试次数


@dataclass
class WorkflowDAG:
    """完整的工作流 DAG。"""
    workflow_id: str
    title: str
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from_id, to_id)
    failure_policy: FailurePolicy = FailurePolicy.SKIP
    timeout_s: float = 600              # 工作流整体超时（10 分钟）
    created_at: float = 0
    status: str = "PENDING"             # PENDING | RUNNING | SUCCEEDED | FAILED | CANCELLED

    def __post_init__(self):
        import time
        if not self.created_at:
            self.created_at = time.monotonic()


@dataclass
class WorkflowStatus:
    """工作流状态快照（API 返回）。"""
    workflow_id: str
    title: str
    status: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    progress: dict[str, int] = field(default_factory=dict)  # {pending, running, succeeded, failed, skipped, cancelled}
    elapsed_s: float = 0
    remaining_s: float = 0


# ═══════════════════════════════════════════════════════════════════
# DAG 工具函数
# ═══════════════════════════════════════════════════════════════════


def has_cycle(nodes: list[str], edges: list[tuple[str, str]]) -> bool:
    """拓扑排序检测 DAG 环路。有环路 → True。"""
    indegree: dict[str, int] = {n: 0 for n in nodes}
    graph: dict[str, list[str]] = defaultdict(list)

    for f, t in edges:
        graph[f].append(t)
        indegree[t] = indegree.get(t, 0) + 1
        indegree.setdefault(f, 0)  # ensure source nodes exist

    q = deque([n for n in indegree if indegree[n] == 0])
    visited = 0
    while q:
        node = q.popleft()
        visited += 1
        for neighbor in graph[node]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                q.append(neighbor)

    return visited != len(indegree)


def topological_levels(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """计算拓扑分层 — 同一层内的节点可并行执行。"""
    indegree: dict[str, int] = {n: 0 for n in nodes}
    graph: dict[str, list[str]] = defaultdict(list)

    for f, t in edges:
        graph[f].append(t)
        indegree[t] = indegree.get(t, 0) + 1
        indegree.setdefault(f, 0)

    levels: list[list[str]] = []
    queue = [n for n in indegree if indegree[n] == 0]

    while queue:
        levels.append(sorted(queue))
        next_queue = []
        for node in queue:
            for neighbor in graph.get(node, []):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    return levels


# ═══════════════════════════════════════════════════════════════════
# WorkflowEngine
# ═══════════════════════════════════════════════════════════════════


@register_connector_v2("workflow_engine")
class WorkflowEngine(AgentConnectorV2):
    """
    轻量 DAG 编排引擎。

    不是替代 OpenAI/Hermes/Anthropic 的"大脑"——它是协调多个 Agent 的编排层。
    当 Commander Agent 需要将复杂任务分解为多步骤工作流时，WorkflowEngine 负责:
      1. 验证 DAG 结构（拒绝环路）
      2. 按拓扑顺序调度节点
      3. 同一层的无依赖节点并行执行
      4. 处理上游失败（根据策略决定下游行为）
      5. 通过 EventBus 实时推送状态
    """

    def __init__(self):
        self._workflows: dict[str, WorkflowDAG] = {}
        self._db: Any = None
        self._event_bus: Any = None
        self._node_executor: Callable[[str, str, str], Awaitable[ActionResult]] | None = None
        self._cleanup_tasks: dict[str, asyncio.Task] = {}

    # ── Identity ──────────────────────────────────────────────────

    def connector_name(self) -> str:
        return "workflow_engine"

    def connector_version(self) -> str:
        return "1.0.0"

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self, agent_config: dict[str, Any]) -> None:
        self._db = agent_config.get("_db")
        self._event_bus = agent_config.get("_event_bus")
        self._node_executor = agent_config.get("_node_executor")

    async def health_check(self) -> bool:
        return True

    async def shutdown(self) -> None:
        for task in self._cleanup_tasks.values():
            task.cancel()
        self._cleanup_tasks.clear()
        self._workflows.clear()

    # ── Capability ────────────────────────────────────────────────

    def capability_inventory(self) -> CapabilityInventory:
        return CapabilityInventory(
            framework="workflow_engine",
            multi_agent_orchestration=True,
            sub_agent_delegation=True,
            text_generation=False,
            file_read=False,
            file_write=False,
            shell_execution=False,
            supported_tools=["delegate_task", "create_workflow", "cancel_workflow"],
        )

    def tool_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="create_workflow",
                description="Create a DAG workflow decomposing a complex task into subtasks. "
                            "Each node is assigned to an agent. Nodes without dependencies run in parallel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Workflow title"},
                        "nodes": {
                            "type": "array", "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "agent_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                        "edges": {
                            "type": "array", "items": {
                                "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2,
                            },
                        },
                        "failure_policy": {"type": "string", "enum": ["skip", "continue", "abort"]},
                    },
                },
                permission=ToolPermission.DELEGATE_TASK,
                risk_level=RiskLevel.MEDIUM,
            ),
            ToolDefinition(
                name="cancel_workflow",
                description="Cancel a running workflow.",
                parameters={
                    "type": "object",
                    "properties": {"workflow_id": {"type": "string"}},
                    "required": ["workflow_id"],
                },
                permission=ToolPermission.DELEGATE_TASK,
                risk_level=RiskLevel.LOW,
            ),
        ]

    # ── Core: act() [作为 Connector 的入口] ───────────────────────

    async def act(
        self,
        context: ConversationContext,
        soul_profile: Any,
        memory_context: MemorySnapshot,
        event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> ActionResult:
        """作为 Connector 的入口 — 由 ConnectorRouter 调用。"""
        # WorkflowEngine 本身不做推理，只做编排。
        # 当 Commander Agent 调用 WorkflowEngine 时，这是 create_workflow 的入口。
        # 目前 MVP: 返回能力说明
        return ActionResult(
            text="WorkflowEngine is ready. Use the 'create_workflow' tool to define and execute DAG workflows.",
            success=True,
        )

    async def act_stream(self, context, soul_profile, memory_context, event_callback=None):
        result = await self.act(context, soul_profile, memory_context, event_callback)
        yield result.text

    # ── Public API ────────────────────────────────────────────────

    async def create_workflow(
        self,
        title: str,
        nodes: list[dict[str, Any]],
        edges: list[tuple[str, str]] | None = None,
        failure_policy: FailurePolicy = FailurePolicy.SKIP,
        timeout_s: float = 600,
        auto_start: bool = True,
    ) -> str:
        """创建并验证一个工作流 DAG。

        Args:
            title: 工作流名称
            nodes: [{"id": "A", "agent_id": "...", "title": "...", "description": "..."}, ...]
            edges: [("A", "B"), ...] — 依赖关系
            failure_policy: 上游失败时的下游策略
            timeout_s: 整体超时时间
            auto_start: 是否自动开始执行

        Returns:
            workflow_id

        Raises:
            ValueError: DAG 有环路
        """
        edges = edges or []
        node_ids = [n["id"] for n in nodes]

        # 验证
        if has_cycle(node_ids, edges):
            raise ValueError(
                f"Workflow DAG contains a cycle. "
                f"Nodes: {node_ids}, Edges: {edges}"
            )

        wf_id = f"wf-{uuid.uuid4().hex[:12]}"

        wf_nodes = {}
        for n in nodes:
            wf_nodes[n["id"]] = WorkflowNode(
                id=n["id"],
                agent_id=n.get("agent_id", ""),
                title=n.get("title", ""),
                description=n.get("description", ""),
            )

        dag = WorkflowDAG(
            workflow_id=wf_id,
            title=title,
            nodes=wf_nodes,
            edges=edges,
            failure_policy=failure_policy,
            timeout_s=timeout_s,
        )

        self._workflows[wf_id] = dag

        logger.info(
            "Workflow created: %s (%d nodes, %d edges)",
            wf_id, len(wf_nodes), len(edges),
        )

        if auto_start:
            asyncio.create_task(self._execute(wf_id))

        return wf_id

    async def get_status(self, workflow_id: str) -> WorkflowStatus | None:
        """获取工作流执行状态。"""
        dag = self._workflows.get(workflow_id)
        if not dag:
            return None

        import time
        nodes_status = []
        progress = defaultdict(int)

        for node in dag.nodes.values():
            progress[node.status.value] += 1
            nodes_status.append({
                "id": node.id,
                "agent_id": node.agent_id,
                "title": node.title,
                "status": node.status.value,
                "result": node.result.text[:200] if node.result else "",
                "error": node.error_message[:200],
            })

        elapsed = time.monotonic() - dag.created_at

        return WorkflowStatus(
            workflow_id=workflow_id,
            title=dag.title,
            status=dag.status,
            nodes=nodes_status,
            progress=dict(progress),
            elapsed_s=elapsed,
            remaining_s=max(0, dag.timeout_s - elapsed),
        )

    async def cancel(self, workflow_id: str) -> bool:
        """取消工作流。"""
        dag = self._workflows.get(workflow_id)
        if not dag:
            return False

        dag.status = "CANCELLED"
        for node in dag.nodes.values():
            if node.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                node.status = NodeStatus.CANCELLED

        # 取消清理任务
        task = self._cleanup_tasks.pop(workflow_id, None)
        if task:
            task.cancel()

        logger.info("Workflow cancelled: %s", workflow_id)
        return True

    def list_workflows(self) -> list[dict[str, Any]]:
        """列出所有工作流（活跃 + 已完成）。"""
        return [
            {
                "workflow_id": wf.workflow_id,
                "title": wf.title,
                "status": wf.status,
                "nodes": len(wf.nodes),
            }
            for wf in self._workflows.values()
        ]

    # ── 执行引擎 ─────────────────────────────────────────────────

    async def _execute(self, workflow_id: str) -> None:
        """执行工作流 DAG。"""
        dag = self._workflows.get(workflow_id)
        if not dag:
            return

        dag.status = "RUNNING"
        logger.info("Workflow executing: %s", workflow_id)

        try:
            import time
            node_ids = list(dag.nodes.keys())

            # 计算拓扑分层
            levels = topological_levels(node_ids, dag.edges)

            for level_idx, level in enumerate(levels):
                # 检查超时
                elapsed = time.monotonic() - dag.created_at
                if elapsed > dag.timeout_s:
                    await self._timeout_workflow(workflow_id)
                    return

                # 检查工作流是否已被取消
                if dag.status == "CANCELLED":
                    return

                # 当前层所有节点可以并行执行
                tasks = []
                for node_id in level:
                    node = dag.nodes[node_id]
                    if node.status == NodeStatus.CANCELLED:
                        continue

                    # 检查上游是否有失败的
                    upstream_failed = self._check_upstream_failed(node_id, dag)
                    if upstream_failed:
                        if dag.failure_policy == FailurePolicy.SKIP:
                            node.status = NodeStatus.SKIPPED
                            await self._push_node_event(node, dag.title)
                            continue
                        elif dag.failure_policy == FailurePolicy.ABORT:
                            await self._abort_downstream(node_id, dag)
                            dag.status = "FAILED"
                            return
                        # CONTINUE: 继续执行（用上游错误作为上下文）

                    tasks.append(self._execute_node(node_id, workflow_id))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                # 检查当前层执行结果
                all_skipped_or_done = all(
                    dag.nodes[nid].status in (NodeStatus.SUCCEEDED, NodeStatus.SKIPPED, NodeStatus.CANCELLED)
                    for nid in level
                )
                if not all_skipped_or_done:
                    failed_nodes = [
                        nid for nid in level
                        if dag.nodes[nid].status == NodeStatus.FAILED
                    ]
                    if failed_nodes:
                        logger.warning(
                            "Workflow %s level %d: nodes %s failed, policy=%s",
                            workflow_id, level_idx, failed_nodes, dag.failure_policy.value,
                        )
                        if dag.failure_policy == FailurePolicy.ABORT:
                            await self._abort_downstream(failed_nodes[0], dag)
                            dag.status = "FAILED"
                            return

            # 所有层完成
            if dag.status == "RUNNING":
                dag.status = "SUCCEEDED"
            logger.info("Workflow complete: %s → %s", workflow_id, dag.status)

        except Exception as e:
            logger.error("Workflow %s execution error: %s", workflow_id, e, exc_info=True)
            dag.status = "FAILED"
            for node in dag.nodes.values():
                if node.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                    node.status = NodeStatus.FAILED
                    node.error_message = str(e)

    async def _execute_node(self, node_id: str, workflow_id: str) -> None:
        """执行单个节点。"""
        dag = self._workflows.get(workflow_id)
        if not dag:
            return

        node = dag.nodes[node_id]
        if node.status in (NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.SKIPPED, NodeStatus.CANCELLED):
            return

        import time
        node.status = NodeStatus.RUNNING
        node.started_at = time.monotonic()

        await self._push_node_event(node, dag.title)

        try:
            if self._node_executor and node.agent_id:
                result = await self._node_executor(node.agent_id, node.title, node.description)
            else:
                # 无 executor 时返回占位结果（测试模式）
                await asyncio.sleep(0.1)  # 模拟执行
                result = ActionResult(
                    text=f"[Node {node_id}] {node.title}: completed (no executor)",
                    success=True,
                )

            node.result = result
            if result.success:
                node.status = NodeStatus.SUCCEEDED
            else:
                node.status = NodeStatus.FAILED
                node.error_message = result.error_message

        except Exception as e:
            node.status = NodeStatus.FAILED
            node.error_message = str(e)
            logger.warning("Node %s failed: %s", node_id, e)

        node.ended_at = time.monotonic()
        await self._push_node_event(node, dag.title)

    # ── 失败处理 ─────────────────────────────────────────────────

    def _check_upstream_failed(self, node_id: str, dag: WorkflowDAG) -> bool:
        """检查节点的上游是否有失败的。"""
        for from_id, to_id in dag.edges:
            if to_id == node_id:
                upstream = dag.nodes.get(from_id)
                if upstream and upstream.status == NodeStatus.FAILED:
                    return True
        return False

    async def _abort_downstream(self, from_node_id: str, dag: WorkflowDAG) -> None:
        """递归取消失败节点的所有下游。"""
        downstream = [to_id for f, to_id in dag.edges if f == from_node_id]
        for ds_id in downstream:
            node = dag.nodes.get(ds_id)
            if node and node.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                node.status = NodeStatus.CANCELLED
                await self._push_node_event(node, dag.title)
                await self._abort_downstream(ds_id, dag)

    async def _timeout_workflow(self, workflow_id: str) -> None:
        """超时处理。"""
        dag = self._workflows.get(workflow_id)
        if not dag:
            return
        dag.status = "CANCELLED"
        for node in dag.nodes.values():
            if node.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                node.status = NodeStatus.CANCELLED
        logger.warning("Workflow %s timed out", workflow_id)

    # ── 事件推送 ─────────────────────────────────────────────────

    async def _push_node_event(self, node: WorkflowNode, workflow_title: str) -> None:
        """推送节点状态变更事件。"""
        if not self._event_bus:
            return
        try:
            from event_bus import AgentEvent as BusEvent, AgentEventType as BusType
            await self._event_bus.publish(BusEvent(
                agent_id=node.agent_id or "workflow",
                agent_name=workflow_title,
                event_type=BusType.PROGRESS if node.status == NodeStatus.RUNNING else BusType.AGENT_DONE,
                payload={
                    "node_id": node.id,
                    "title": node.title,
                    "status": node.status.value,
                    "result": node.result.text[:200] if node.result else "",
                },
            ))
        except Exception:
            pass  # 事件推送不应阻塞执行
