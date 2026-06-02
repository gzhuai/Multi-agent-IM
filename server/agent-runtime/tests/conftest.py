"""
测试 Fixtures 和共享配置。

运行: pytest tests/ -x -v
跳过LLM调用: pytest tests/ -x -v -m "not llm"
仅单元测试: pytest src/ -x -v -m "not integration"
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# Test Data Factories
# ============================================================

def make_agent_profile(**overrides) -> dict:
    """创建标准的测试用 Agent 配置"""
    defaults = {
        "name": "测试Agent",
        "role": "测试工程师",
        "department": "质量保障部",
        "level": 5,
        "persona": {
            "openness": 0.5,
            "conscientiousness": 0.9,
            "extraversion": 0.3,
            "agreeableness": 0.7,
            "neuroticism": 0.2,
            "communication": {
                "verbosity": 0.5,
                "formality": 0.5,
                "humor": 0.1,
                "directness": 0.7,
            },
            "decision_making": {
                "risk_tolerance": 0.3,
                "data_driven": 0.8,
                "speed_accuracy": 0.4,
                "autonomy": 0.6,
            },
        },
        "values": {
            "core_principles": ["质量优先", "实事求是"],
            "red_lines": [
                "不能修改生产数据库",
                "不能跳过测试直接上线",
            ],
        },
    }
    defaults.update(overrides)
    return defaults


def make_conversation_context(**overrides) -> dict:
    """创建标准的测试用对话上下文"""
    defaults = {
        "channel_id": "ch_test_001",
        "messages": [
            {"role": "user", "content": "你好，请帮我分析一下这个需求的可行性"},
        ],
        "participants": [
            {"id": "user_1", "type": "human", "name": "张总"},
            {"id": "agent_1", "type": "agent", "name": "测试Agent"},
        ],
        "mentioned": True,
    }
    defaults.update(overrides)
    return defaults


def make_memory_snapshot(**overrides) -> dict:
    """创建标准的测试用记忆快照"""
    defaults = {
        "episodic": [
            {
                "event": "完成了用户画像功能的测试用例编写",
                "timestamp": "2024-06-01T10:00:00",
                "importance": 0.7,
            },
        ],
        "semantic": [
            {
                "knowledge": "用户画像模块采用微服务架构",
                "source": "项目文档",
                "confidence": 0.9,
            },
        ],
        "relational": [
            {
                "target_id": "user_1",
                "name": "张总",
                "trust": 0.75,
                "notes": "重视测试覆盖率",
            },
        ],
    }
    defaults.update(overrides)
    return defaults


# ============================================================
# Pytest Fixtures
# ============================================================

@pytest.fixture
def sample_agent_profile():
    """标准测试用 Agent 配置"""
    return make_agent_profile()


@pytest.fixture
def strict_agent_profile():
    """严格的 Agent 配置 —— 高红线意识"""
    return make_agent_profile(
        name="严格Agent",
        values={
            "core_principles": ["安全第一"],
            "red_lines": [
                "不能修改生产数据库",
                "不能向外部发送数据",
                "不能创建超过1000元的采购单",
            ],
        },
    )


@pytest.fixture
def conversation_context():
    """标准测试用对话上下文"""
    return make_conversation_context()


@pytest.fixture
def memory_snapshot():
    """标准测试用记忆快照"""
    return make_memory_snapshot()


@pytest.fixture
def mock_llm_client(mocker):
    """Mock Anthropic 客户端，返回固定的回复"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            type="text",
            text="这是一个测试回复。根据我的分析，这个需求整体可行。"
        )
    ]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mocker.patch(
        "anthropic.AsyncAnthropic",
        return_value=mock_client,
    )
    return mock_client


@pytest.fixture
def mock_llm_response_with_tool_use():
    """Mock Anthropic 返回工具调用"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(type="text", text="我需要查询数据库。"),
        MagicMock(
            type="tool_use",
            id="tool_001",
            name="query_database",
            input={"sql": "SELECT COUNT(*) FROM users"},
        ),
    ]
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client
