"""
Soul Engine 单元测试 —— 灵魂系统的核心逻辑验证。

TDD 原则:
  - 这些测试在实现代码之前编写
  - 当前全部 RED (失败)，随着功能实现逐步 GREEN
  - 每个测试验证一个明确的行为契约
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================
# Soul Profile 组装测试
# ============================================================

class TestSoulProfileAssembly:
    """验证 Soul Profile 的数据完整性和配置正确性"""

    def test_profile_contains_all_required_sections(self, sample_agent_profile):
        """验证 Agent 配置包含所有必需字段"""
        required_sections = ["name", "role", "persona", "values"]
        for section in required_sections:
            assert section in sample_agent_profile, f"缺少必需字段: {section}"

    def test_persona_traits_are_in_valid_range(self, sample_agent_profile):
        """验证人格特质值在 [0.0, 1.0] 范围内"""
        traits = sample_agent_profile["persona"]
        trait_names = [
            "openness", "conscientiousness", "extraversion",
            "agreeableness", "neuroticism"
        ]
        for trait in trait_names:
            value = traits.get(trait, 0.5)
            assert 0.0 <= value <= 1.0, f"{trait} 超出范围: {value}"

    def test_red_lines_are_non_empty_for_production_agent(self):
        """验证正式 Agent 必须配置至少一条红线"""
        profile = {
            "name": "无约束Agent",
            "values": {"red_lines": []}
        }
        # 在生产模式 (非 sandbox) 下应该拒绝空红线配置
        # 测试框架下此断言为 RED，等待实现
        from soul_engine.profile import validate_agent_profile  # noqa — 导入待实现
        with pytest.raises(ValueError, match="生产Agent必须配置至少一条红线"):
            validate_agent_profile(profile, mode="production")


# ============================================================
# System Prompt 构建测试
# ============================================================

class TestSystemPromptBuilding:
    """验证 Persona → System Prompt 的转换正确性"""

    def test_high_directness_produces_direct_language(self):
        """高直接度 → Prompt 中包含'直接'相关指令"""
        profile = {
            "name": "直率Agent",
            "persona": {
                "communication": {"directness": 0.9}
            }
        }
        # prompt = build_system_prompt(profile, context={}, memories=[])
        # assert "直接" in prompt
        # assert "直截了当" in prompt or "不要拐弯抹角" in prompt
        pytest.skip("等待 SoulEngine.build_system_prompt 实现")

    @pytest.mark.parametrize("risk_level,expected_tone", [
        (0.1, "conservative"),
        (0.5, "balanced"),
        (0.9, "aggressive"),
    ])
    def test_risk_tolerance_maps_to_correct_tone(
        self, risk_level, expected_tone
    ):
        """验证风险偏好正确映射到决策提示"""
        pytest.skip("等待 Persona.render_decision_guidance 实现")

    def test_red_lines_appear_in_system_prompt(self, strict_agent_profile):
        """验证红线约束被明确注入到 System Prompt 中"""
        pytest.skip("等待 SoulEngine.build_system_prompt 实现")


# ============================================================
# 红线检查测试
# ============================================================

class TestRedLineChecking:
    """验证 Agent 动作是否违反红线"""

    def test_db_write_to_production_triggers_violation(self):
        """修改生产数据库 → 触发违规"""
        from soul_engine.profile import check_red_lines  # noqa
        red_lines = ["不能修改生产数据库"]
        action = {"type": "db_write", "target": "production"}

        violations = check_red_lines(red_lines, action)
        assert len(violations) >= 1

    def test_db_write_to_staging_passes(self):
        """修改测试数据库 → 不触发违规"""
        from soul_engine.profile import check_red_lines  # noqa
        red_lines = ["不能修改生产数据库"]
        action = {"type": "db_write", "target": "staging"}

        violations = check_red_lines(red_lines, action)
        assert len(violations) == 0

    def test_external_data_send_triggers_violation(self):
        """向外部发送数据 → 触发违规"""
        from soul_engine.profile import check_red_lines  # noqa
        red_lines = ["不能向外部发送内部数据"]
        action = {"type": "http_post", "url": "https://external-api.com/upload"}

        violations = check_red_lines(red_lines, action)
        assert len(violations) >= 1

    def test_multiple_violations_all_returned(self):
        """一个动作可能同时触发多条红线"""
        from soul_engine.profile import check_red_lines  # noqa
        red_lines = [
            "不能修改生产数据库",
            "不能未经审批执行删除操作",
        ]
        action = {
            "type": "db_delete",
            "target": "production",
            "approved": False,
        }

        violations = check_red_lines(red_lines, action)
        assert len(violations) == 2


# ============================================================
# Memory 检索测试
# ============================================================

class TestMemoryRetrieval:
    """验证记忆检索的正确性"""

    def test_retrieval_returns_top_k_by_importance(self):
        """验证返回重要度最高的 K 条记忆"""
        from soul_engine.memory import retrieve_episodic_memories  # noqa
        memories = [
            {"event": "早餐吃了什么", "importance": 0.1},
            {"event": "项目上线", "importance": 0.9},
            {"event": "修了一个关键Bug", "importance": 0.8},
            {"event": "参加了一场会", "importance": 0.3},
        ]

        result = retrieve_episodic_memories(memories, k=2)
        assert len(result) == 2
        assert result[0]["event"] == "项目上线"
        assert result[1]["event"] == "修了一个关键Bug"

    def test_empty_memory_returns_empty_list(self):
        """空记忆返回空列表，不报错"""
        from soul_engine.memory import retrieve_episodic_memories  # noqa
        result = retrieve_episodic_memories([], k=5)
        assert result == []

    def test_memory_decay_reduces_importance(self):
        """验证记忆衰减降低重要度"""
        from soul_engine.memory import apply_decay  # noqa
        memory = {"importance": 0.8, "last_accessed": "2024-01-01T00:00:00"}

        decayed = apply_decay(memory, current_time="2024-07-01T00:00:00")
        assert decayed["importance"] < 0.8
