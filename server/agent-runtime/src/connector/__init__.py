# v1 Connectors (deprecated after Phase 2 — kept for backward compat)
from connector.claude_code import ClaudeCodeConnector  # noqa: F401
from connector.openai_compatible import OpenAICompatibleConnector  # noqa: F401

# v2 Connectors (new framework agents)
from connector.anthropic_agent import AnthropicAgentConnector  # noqa: F401
# WorkflowEngine registered via connector_router.py (avoids circular import)
