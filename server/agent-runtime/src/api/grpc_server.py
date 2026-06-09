"""
Agent Runtime HTTP API server.

Phase 1 uses HTTP REST (for quick integration).
Phase 2+ migrates to gRPC using the generated proto stubs.
"""

import asyncio
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from agent_runtime.config import Config
from agent_runtime.db import Database
from agent_runtime.agent_service import AgentService
from agent_runtime.reasoning_engine import ReasoningEngine
from agent_runtime.metrics import get_metrics
from connector_router import ConnectorRouter, RoutingResult

logger = logging.getLogger(__name__)


class AgentAPIHandler(BaseHTTPRequestHandler):
    db: Database = None
    agent_service: AgentService = None
    reasoning_engine: ReasoningEngine = None
    connector_router: ConnectorRouter = None  # v2: 双轨路由器
    _loop: asyncio.AbstractEventLoop = None

    @classmethod
    def _get_loop(cls):
        if cls._loop is None or cls._loop.is_closed():
            cls._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(cls._loop)
        return cls._loop

    @staticmethod
    def _run(coro):
        loop = AgentAPIHandler._get_loop()
        return loop.run_until_complete(coro)

    def do_GET(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query or "")

        if path == "/health":
            self._json(200, {"status": "ok", "service": "agent-runtime"})

        elif path == "/api/metrics/frameworks":
            m = get_metrics()
            self._json(200, {
                "frameworks": m.compare_frameworks(),
                "recent_calls": m.recent_calls(10),
            })

        elif path == "/api/agents":
            agents = self._run(self.agent_service.list_agents())
            self._json(200, {"agents": agents})

        elif path.startswith("/api/agents/") and path.endswith("/memories"):
            agent_id = path.split("/")[3]
            tier = params.get("tier", ["working"])[0]
            limit = int(params.get("limit", ["50"])[0])
            memories = self._run(self.db.get_all_memories(agent_id, limit=limit))
            self._json(200, {"memories": memories, "agent_id": agent_id})

        elif path.startswith("/api/memories/") and path.endswith("/search"):
            memory_id = path.split("/")[3]
            query = params.get("q", [""])[0]
            # Simple query-based search across all agent memories
            self._json(404, {"error": "use POST /api/agents/{id}/memories/recall for semantic search"})

        elif path.startswith("/api/agents/") and path.endswith("/connector"):
            agent_id = path.split("/")[3]
            agent = self._run(self.agent_service.get_agent(agent_id))
            if agent:
                self._json(200, {
                    "agent_id": agent_id,
                    "connector_type": agent.get("connector_type", "claude_code"),
                    "connector_config": agent.get("connector_config", {}),
                })
            else:
                self._json(404, {"error": "agent not found"})

        elif path.startswith("/api/agents/") and path.endswith("/status"):
            agent_id = path.split("/")[3]
            agent = self._run(self.agent_service.get_agent(agent_id))
            if agent:
                self._json(200, {"id": agent["id"], "status": agent["status"]})
            else:
                self._json(404, {"error": "agent not found"})

        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/agents":
            result = self._run(self.agent_service.create_agent(body))
            # Inject knowledge documents into agent memory
            docs = body.get("knowledge_documents", [])
            if docs:
                agent_id = result["id"]
                for doc in docs:
                    self._run(self.agent_service.inject_knowledge_document(
                        agent_id, doc.get("name", "doc.md"), doc.get("content", "")
                    ))
            self._json(201, result)

        elif path.startswith("/api/agents/") and path.endswith("/connector"):
            agent_id = path.split("/")[3]
            new_type = body.get("connector_type", "openai_compatible")
            new_config = body.get("connector_config", {})
            # Persist to DB
            self._run(self.db.update_agent_connector(agent_id, new_type, new_config))
            self._json(200, {
                "ok": True,
                "agent_id": agent_id,
                "connector_type": new_type,
            })

        elif path.startswith("/api/agents/") and path.endswith("/activate"):
            agent_id = path.split("/")[3]
            try:
                status = self._run(self.agent_service.activate_agent(agent_id))
                self._json(200, {"id": agent_id, "status": status})
            except ValueError as e:
                self._json(404, {"error": str(e)})

        elif path.startswith("/api/agents/") and path.endswith("/pause"):
            agent_id = path.split("/")[3]
            status = self._run(self.agent_service.pause_agent(agent_id))
            self._json(200, {"id": agent_id, "status": status})

        elif path.startswith("/api/agents/") and path.endswith("/resume"):
            agent_id = path.split("/")[3]
            status = self._run(self.agent_service.resume_agent(agent_id))
            self._json(200, {"id": agent_id, "status": status})

        elif path == "/api/agents/activity":
            # Update agent's current activity for task-level granularity
            agent_id = body.get("agent_id")
            activity = body.get("activity", "")
            task_count = body.get("task_count")
            self._run(self.agent_service.update_activity(agent_id, activity, task_count))
            self._json(200, {"ok": True})

        elif path == "/api/tasks/enqueue":
            # Enqueue a task for an agent with priority (preemptive scheduling)
            result = self._run(self.agent_service.enqueue_task(
                agent_id=body["agent_id"],
                task=body["task"],
                priority=body.get("priority", "NORMAL"),
            ))
            self._json(201, result)

        elif path.startswith("/api/tasks/") and path.endswith("/dequeue"):
            # Get next task respecting priority order
            agent_id = path.split("/")[3]
            task = self._run(self.agent_service.dequeue_task(agent_id))
            if task:
                self._json(200, task)
            else:
                self._json(204, {"message": "no tasks queued"})

        elif path.startswith("/api/tasks/") and path.endswith("/execute"):
            # ── v2: 任务执行端点 — ConnectorRouter 双轨路由 ──
            agent_id = body.get("agent_id")
            task_title = body.get("title", "")
            task_desc = body.get("description", "")
            if not agent_id:
                self._json(400, {"error": "agent_id required"})
                return
            result: RoutingResult = self._run(
                self.connector_router.route(
                    agent_id=agent_id,
                    channel_id=body.get("channel_id", ""),
                    messages=[{
                        "role": "user",
                        "content": f"Execute task: {task_title}\n\n{task_desc}",
                        "sender_name": "task-system",
                    }],
                    participants=body.get("participants", []),
                )
            )
            self._json(200, self._serialize_routing_result(result))

        elif path.startswith("/api/tasks/") and path.endswith("/decompose"):
            # LLM decomposes a task into subtasks
            agent_id = body.get("agent_id", "")
            task_title = body.get("title", "")
            task_desc = body.get("description", "")
            from agent_runtime.task_decomposer import decompose_task
            all_agents = self._run(self.agent_service.list_agents(
                org_id="2b711d7c-29b1-429c-b61d-e93ddaa46e41"
            ))
            result = self._run(decompose_task(
                agent_id=agent_id,
                task_title=task_title,
                task_description=task_desc,
                available_agents=all_agents,
                reasoning_engine=self.reasoning_engine,
            ))
            self._json(200, {
                "subtasks": [
                    {"title": s.title, "description": s.description,
                     "suggested_assignee": s.suggested_assignee, "priority": s.priority}
                    for s in result.subtasks
                ],
                "reasoning": result.reasoning,
            })

        elif path.startswith("/api/agents/") and path.endswith("/memories/recall"):
            # Semantic memory search
            agent_id = path.split("/")[3]
            query = body.get("query", "")
            tier = body.get("tier", "working")
            limit = body.get("limit", 10)
            from soul_engine.memory import generate_embedding, semantic_search
            memories = self._run(self.db.get_all_memories(agent_id, limit=200))
            results = semantic_search(query, memories, top_k=limit)
            self._json(200, {"results": results, "query": query, "count": len(results)})

        elif path.startswith("/api/memories/") and path.endswith("/promote"):
            memory_id = path.split("/")[3]
            new_tier = body.get("tier", "core")
            ok = self._run(self.db.update_memory_tier(memory_id, new_tier))
            self._json(200, {"ok": ok, "tier": new_tier})

        elif path.startswith("/api/memories/") and path.endswith("/archive"):
            memory_id = path.split("/")[3]
            ok = self._run(self.db.update_memory_tier(memory_id, "archived"))
            self._json(200, {"ok": ok, "tier": "archived"})

        elif path.startswith("/api/agents/") and path.endswith("/retrospect"):
            # Agent self-reflection
            agent_id = path.split("/")[3]
            from agent_runtime.retrospect import run_retrospect
            period_days = body.get("period_days", 7)
            report = self._run(run_retrospect(
                agent_id=agent_id,
                period_days=period_days,
                db=self.db,
                agent_service=self.agent_service,
                reasoning_engine=self.reasoning_engine,
            ))
            self._json(200, report)

        elif path == "/api/think":
            # ── v2: 核心推理端点 — ConnectorRouter 双轨路由 ──
            result: RoutingResult = self._run(
                self.connector_router.route(
                    agent_id=body["agent_id"],
                    channel_id=body.get("channel_id", ""),
                    messages=body.get("messages", []),
                    participants=body.get("participants", []),
                )
            )
            self._json(200, self._serialize_routing_result(result))

        elif path == "/api/wake":
            # ── v2: 自主唤醒端点 — ConnectorRouter 双轨路由 ──
            result: RoutingResult = self._run(
                self.connector_router.route_wake(
                    agent_id=body["agent_id"],
                    channel_id=body.get("channel_id", ""),
                    participants=body.get("participants", []),
                )
            )
            self._json(200, self._serialize_routing_result(result))

        elif path == "/api/think/stream":
            # ── v2: 流式推理端点 — ConnectorRouter 双轨路由 ──
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            async def stream():
                async for chunk in self.connector_router.route_stream(
                    agent_id=body["agent_id"],
                    channel_id=body.get("channel_id", ""),
                    messages=body.get("messages", []),
                    participants=body.get("participants", []),
                ):
                    self.wfile.write(f"data: {json.dumps({'text': chunk})}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")

            self._run(stream())

        else:
            self._json(404, {"error": "not found"})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def _json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _serialize_routing_result(self, result: RoutingResult) -> dict:
        """将 RoutingResult 序列化为 API 响应 JSON。兼容 v1 的 {text, actions, memory_saved}。"""
        response: dict = {
            "text": result.text,
            "actions": result.actions,
            "memory_saved": result.memory_saved,
        }
        if result.tool_executions:
            response["tool_executions"] = result.tool_executions
        if result.file_changes:
            response["file_changes"] = result.file_changes
        if result.reasoning_trace:
            response["reasoning_trace"] = result.reasoning_trace
        if result.route_decision:
            response["_route"] = {
                "connector": result.route_decision.connector_type_v2 or "v1",
                "path": result.route_decision.route,
                "reason": result.route_decision.reason,
            }
        if result.error:
            response["error"] = result.error
        return response

    def log_message(self, format, *args):
        logger.debug(format % args)


class AgentRuntimeServer:
    def __init__(self, cfg: Config, db: Database):
        self.host = "0.0.0.0"
        self.port = cfg.grpc_port
        self.db = db
        self._server: HTTPServer | None = None

        # Create core services
        agent_service = AgentService(db)
        reasoning_engine = ReasoningEngine(db)

        # v2: ConnectorRouter wraps ReasoningEngine for dual-track routing
        connector_router = ConnectorRouter(
            db=db,
            reasoning_engine=reasoning_engine,
        )

        # Inject dependencies into handler
        AgentAPIHandler.db = db
        AgentAPIHandler.agent_service = agent_service
        AgentAPIHandler.reasoning_engine = reasoning_engine
        AgentAPIHandler.connector_router = connector_router

    async def start(self):
        self._server = HTTPServer((self.host, self.port), AgentAPIHandler)
        logger.info(f"Agent Runtime API server on {self.host}:{self.port}")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._server.serve_forever)

    async def stop(self):
        if self._server:
            self._server.shutdown()
            logger.info("Agent Runtime server stopped")
        # v2: shutdown ConnectorRouter (closes all v2 connectors)
        if AgentAPIHandler.connector_router:
            await AgentAPIHandler.connector_router.shutdown()
