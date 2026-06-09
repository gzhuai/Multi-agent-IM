"""
Agent Runtime entry point.
"""

import asyncio
import logging
import os
import signal

from dotenv import load_dotenv

# Load .env from project root (5 levels up from src/agent_runtime/app.py)
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
load_dotenv(os.path.join(_root, ".env"))

from agent_runtime.config import load
from agent_runtime.db import Database
from api.grpc_server import AgentRuntimeServer
import connector  # noqa: F401 — trigger v1 connector registration
import connector.hermes_agent  # noqa: F401
import workflow_engine  # noqa: F401 — trigger v2 registrations (@register_connector_v2)

logger = logging.getLogger(__name__)


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main():
    cfg = load()
    setup_logging(cfg.log_level)

    logger.info("Starting Agent Runtime")
    logger.info(f"LLM: {cfg.llm.provider} | model: {cfg.llm.model}")
    logger.info(f"DB: {cfg.database.host}:{cfg.database.port}/{cfg.database.dbname}")

    # Initialize database
    db = Database(cfg.database)

    server = AgentRuntimeServer(cfg, db)

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    server_task = asyncio.create_task(server.start())

    await stop_event.wait()
    await server.stop()
    server_task.cancel()

    await db.close()
    logger.info("Agent Runtime stopped")


if __name__ == "__main__":
    asyncio.run(main())
