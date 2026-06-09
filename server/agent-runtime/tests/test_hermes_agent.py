"""
Phase 4 HermesAgentConnector 专项测试。

验证:
  1. Connector 注册与接口合规
  2. 工具集映射（permission → Hermes toolsets）
  3. 未安装时优雅降级
  4. act() 返回格式正确
  5. 消息组装逻辑
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from connector.base_v2 import (
    CONNECTOR_REGISTRY_V2,
    get_connector_v2,
    CapabilityInventory,
    RiskLevel,
)

# ═══════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════

class TestRegistration:
    """HermesAgentConnector 在 registry 中。"""

    def test_has_hermes_registered(self):
        assert "hermes_agent" in CONNECTOR_REGISTRY_V2
        cls = get_connector_v2("hermes_agent")
        from connector.hermes_agent import HermesAgentConnector
        assert cls is HermesAgentConnector

    def test_connector_creates_instance(self):
        cls = get_connector_v2("hermes_agent")
        instance = cls()
        assert instance.connector_name() == "hermes_agent"
        assert instance.connector_version() == "1.0.0"


# ═══════════════════════════════════════════════════════════════════
# Toolset Mapping
# ═══════════════════════════════════════════════════════════════════

class TestToolsetMapping:
    """Permission → Hermes toolsets 映射。"""

    def _connector(self):
        from connector.hermes_agent import HermesAgentConnector
        return HermesAgentConnector()

    def test_empty_permissions_returns_empty(self):
        c = self._connector()
        result = c._resolve_toolsets([])
        assert result == []

    def test_file_read_maps_to_file_toolset(self):
        c = self._connector()
        result = c._resolve_toolsets(["file_read", "send_message"])
        assert "file" in result  # file_read → file
        assert "terminal" not in result
        assert "web" not in result

    def test_shell_maps_to_terminal(self):
        c = self._connector()
        result = c._resolve_toolsets(["shell_exec", "shell_install"])
        assert "terminal" in result

    def test_full_permissions_maps_all(self):
        c = self._connector()
        all_perms = ["file_read", "file_write", "shell_exec", "shell_install",
                      "git_read", "git_write"]
        result = c._resolve_toolsets(all_perms)
        assert "file" in result
        assert "terminal" in result

    def test_deduplication(self):
        """多个权限映射到同一 toolset 时不重复。"""
        c = self._connector()
        result = c._resolve_toolsets(["file_read", "file_write", "file_read"])
        assert result.count("file") == 1


# ═══════════════════════════════════════════════════════════════════
# Graceful Degradation
# ═══════════════════════════════════════════════════════════════════

class TestGracefulDegradation:
    """Hermes 未安装时的行为。"""

    def test_connector_imports_despite_no_hermes_installed(self):
        """即使 Hermes 未安装，connector 模块本身仍能导入。"""
        from connector.hermes_agent import (
            HermesAgentConnector, HERMES_AVAILABLE
        )
        # 模块导入成功（不崩溃）
        assert isinstance(HERMES_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_health_check_matches_availability(self):
        """health_check() 返回 HERMES_AVAILABLE 的值。"""
        from connector.hermes_agent import HermesAgentConnector, HERMES_AVAILABLE
        c = HermesAgentConnector()
        await c.initialize({"agent_id": "test", "agent_name": "Test"})
        assert await c.health_check() == HERMES_AVAILABLE

    @pytest.mark.asyncio
    async def test_act_when_not_installed(self):
        """Hermes 未安装时 act() 返回错误信息。"""
        from connector.hermes_agent import HermesAgentConnector, HERMES_AVAILABLE
        from connector.base import ConversationContext, MemorySnapshot

        c = HermesAgentConnector()
        await c.initialize({"agent_id": "test", "agent_name": "Test"})

        result = await c.act(
            ConversationContext(channel_id="ch1", messages=[], participants=[]),
            MagicMock(), MemorySnapshot(),
        )

        if not HERMES_AVAILABLE:
            assert not result.success
            assert "offline" in result.text.lower() or "not installed" in result.text.lower()
        else:
            # 如果安装了 → 跳过（需要真实 Hermes）
            pytest.skip("Hermes Agent is installed — real integration test needed")


# ═══════════════════════════════════════════════════════════════════
# Interface & Capability
# ═══════════════════════════════════════════════════════════════════

class TestCapabilityInventory:
    """CapabilityInventory 正确性。"""

    def test_inventory_reflects_hermes_capabilities(self):
        from connector.hermes_agent import HermesAgentConnector
        c = HermesAgentConnector()
        inv = c.capability_inventory()
        assert inv.framework == "hermes_agent"
        assert inv.file_read is True
        assert inv.file_write is True
        assert inv.shell_execution is True
        assert inv.web_search is True
        assert inv.sub_agent_delegation is True
        assert inv.supported_tools  # 至少有一些工具

    def test_tool_definitions_count(self):
        from connector.hermes_agent import HermesAgentConnector
        c = HermesAgentConnector()
        tools = c.tool_definitions()
        assert len(tools) == 8  # 8 个核心工具
        names = {t.name for t in tools}
        assert "read_file" in names
        assert "terminal" in names
        assert "web_search" in names


# ═══════════════════════════════════════════════════════════════════
# Message Building
# ═══════════════════════════════════════════════════════════════════

class TestMessageBuilding:
    """ConversationContext → Hermes user message 转换。"""

    def test_basic_conversation(self):
        from connector.hermes_agent import HermesAgentConnector
        from connector.base import ConversationContext

        c = HermesAgentConnector()
        ctx = ConversationContext(
            channel_id="ch1",
            messages=[
                {"role": "user", "content": "Hello", "sender_name": "Alice", "sender_type": "human"},
                {"role": "user", "content": "Hi Alice!", "sender_name": "Bob", "sender_type": "agent"},
            ],
        )
        text = c._build_user_message(ctx)
        assert "Alice" in text
        assert "Hello" in text
        assert "(AI)" in text  # Agent 消息标记

    def test_system_messages_filtered(self):
        from connector.hermes_agent import HermesAgentConnector
        from connector.base import ConversationContext

        c = HermesAgentConnector()
        ctx = ConversationContext(
            channel_id="ch1",
            messages=[
                {"role": "system", "content": "config", "sender_name": "system", "sender_type": "system"},
                {"role": "user", "content": "real message", "sender_name": "User1", "sender_type": "human"},
            ],
        )
        text = c._build_user_message(ctx)
        assert "real message" in text
        assert "config" not in text  # system messages excluded
