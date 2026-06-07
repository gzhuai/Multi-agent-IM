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

logger = logging.getLogger(__name__)


class AgentAPIHandler(BaseHTTPRequestHandler):
    db: Database = None
    agent_service: AgentService = None
    reasoning_engine: ReasoningEngine = None
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

        elif path == "/api/agents":
            agents = self._run(self.agent_service.list_agents())
            self._json(200, {"agents": agents})

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

        elif path == "/api/think":
            # Core thinking endpoint — called by IM Core when agent receives a message
            result = self._run(
                self.reasoning_engine.process_message(
                    agent_id=body["agent_id"],
                    channel_id=body.get("channel_id", ""),
                    messages=body.get("messages", []),
                    participants=body.get("participants", []),
                )
            )
            self._json(200, {
                "text": result.text,
                "actions": result.actions,
                "memory_saved": result.memory_saved,
            })

        elif path == "/api/think/stream":
            # Streaming thinking endpoint
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            async def stream():
                async for chunk in self.reasoning_engine.process_message_stream(
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

    def log_message(self, format, *args):
        logger.debug(format % args)


class AgentRuntimeServer:
    def __init__(self, cfg: Config, db: Database):
        self.host = "0.0.0.0"
        self.port = cfg.grpc_port
        self.db = db
        self._server: HTTPServer | None = None

        # Inject dependencies into handler
        AgentAPIHandler.db = db
        AgentAPIHandler.agent_service = AgentService(db)
        AgentAPIHandler.reasoning_engine = ReasoningEngine(db)

    async def start(self):
        self._server = HTTPServer((self.host, self.port), AgentAPIHandler)
        logger.info(f"Agent Runtime API server on {self.host}:{self.port}")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._server.serve_forever)

    async def stop(self):
        if self._server:
            self._server.shutdown()
            logger.info("Agent Runtime server stopped")
