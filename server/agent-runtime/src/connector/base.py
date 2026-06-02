"""
Abstract base class for agent framework connectors.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ConversationContext:
    channel_id: str = ""
    messages: list[dict] = field(default_factory=list)
    participants: list[dict] = field(default_factory=list)
    mentioned: bool = False


@dataclass
class MemorySnapshot:
    episodic: list[dict] = field(default_factory=list)
    semantic: list[dict] = field(default_factory=list)
    relational: list[dict] = field(default_factory=list)


@dataclass
class Thought:
    text: str = ""
    actions: list[dict] = field(default_factory=list)
    reasoning_trace: str = ""


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: dict = field(default_factory=dict)
    error: str | None = None


class AgentConnector(ABC):
    """Unified interface for all agent framework backends."""

    @abstractmethod
    async def initialize(self, agent_config: dict) -> None:
        ...

    @abstractmethod
    async def think(
        self, context: ConversationContext, memory: MemorySnapshot
    ) -> Thought:
        ...

    @abstractmethod
    async def think_stream(
        self, context: ConversationContext, memory: MemorySnapshot
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    async def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        ...

    @abstractmethod
    def capabilities(self) -> list[str]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...


# Connector registry
CONNECTOR_REGISTRY: dict[str, type[AgentConnector]] = {}


def register_connector(name: str):
    """Decorator to register a connector implementation."""
    def wrapper(cls: type[AgentConnector]):
        CONNECTOR_REGISTRY[name] = cls
        return cls
    return wrapper


def get_connector(name: str) -> type[AgentConnector]:
    if name not in CONNECTOR_REGISTRY:
        raise ValueError(f"Unknown connector: {name}. Available: {list(CONNECTOR_REGISTRY)}")
    return CONNECTOR_REGISTRY[name]
