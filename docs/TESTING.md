# 测试规范与TDD开发指南

## 分层测试策略

```
┌─────────────────────────────────────────────────────────────┐
│                    测试金字塔 (Multi-agent-IM)               │
│                                                             │
│        ┌──────────┐                                         │
│        │  E2E     │  全链路场景测试 (少量, 慢, 最有信心)     │
│        │  Scenarios│  Agent协作 / 消息全链路 / 任务闭环      │
│        └────┬─────┘                                         │
│             │                                               │
│      ┌──────┴──────┐                                        │
│      │  Integration │  跨模块集成测试 (适量, 中速)           │
│      │   Tests      │  DB读写 / API契约 / Agent-IM通信      │
│      └──────┬──────┘                                        │
│             │                                               │
│    ┌────────┴────────┐                                      │
│    │   Unit Tests    │  单元测试 (大量, 快速, TDD核心区)     │
│    │                 │  业务逻辑 / 状态机 / 消息路由 /       │
│    │                 │  灵魂引擎 / 数据转换                  │
│    └─────────────────┘                                      │
└─────────────────────────────────────────────────────────────┘
```

## 各层测试职责

### 1. 单元测试 (Unit Tests) —— TDD 主力区

**范围**: 纯逻辑，不涉及网络/IO/外部依赖

**Go 侧重点**:
- 消息路由与分发逻辑
- 权限校验规则
- 频道管理逻辑
- WebSocket 连接状态机
- 任务状态流转
- 数据序列化/反序列化
- API 参数校验

**Python 侧重点**:
- Soul Profile 组装与注入
- Memory 检索与排序算法
- 人格参数如何影响 Prompt 生成
- Value System 红线检查
- Connector 适配层数据转换
- Agent 状态机流转

**前端侧重点** (仅业务逻辑层):
- 状态管理 (Zustand store 的 reducer 逻辑)
- 工具函数与数据格式化
- Hook 逻辑

**规则**:
- 每个测试只测一个行为
- 测试命名: `Test<函数名>_<场景>_<期望结果>`
- 使用 Table-Driven Tests (Go) / parametrize (Python)
- Mock 所有外部依赖 (DB, HTTP, LLM API)
- 单次运行 < 100ms

### 2. 集成测试 (Integration Tests)

**范围**: 模块间交互，含真实依赖或可控模拟

- Repository 层对真实测试数据库读写
- API Handler 完整请求-响应链路
- Agent Runtime ↔ IM Engine 的 gRPC 调用
- Redis Pub/Sub 消息传递
- Agent 调用真实 LLM API 的沙盒测试（使用测试 API Key 和限速）

**规则**:
- 使用 Docker Compose 启动测试依赖 (PostgreSQL, Redis)
- 每个测试有独立的数据库事务，测试结束回滚
- 单次运行 < 500ms（LLM 调用测试除外）
- 不依赖测试执行顺序

### 3. 端到端测试 (E2E)

**范围**: 完整用户场景

- 创建 Agent → 配置灵魂 → 发送消息 → Agent 回复 → 消息在 UI 中显示
- 多 Agent 频道协作场景
- 任务创建 → 分配 → 执行 → 完成闭环

**规则**:
- 仅覆盖核心业务路径 (P0 场景)，不追求覆盖率
- 可在 CI 中按需运行 (PR 合并前触发)

---

## TDD 工作流 (Red-Green-Refactor)

### 标准流程

```
Step 1: 写一个失败的测试
  ├── 明确当前要实现什么
  ├── 写出"当...时，应该..."的测试用例
  └── 运行测试 → 红灯 (FAIL)

Step 2: 写最少代码让测试通过
  ├── 不追求代码质量，只追求通过测试
  ├── 允许硬编码、复制粘贴
  └── 运行测试 → 绿灯 (PASS)

Step 3: 重构
  ├── 消除重复代码
  ├── 提取抽象
  ├── 优化命名
  └── 运行测试 → 仍然绿灯 (PASS) → 提交
```

### 提交节奏

```
一个 TDD 循环 ≈ 一次 commit
commit message 格式:
  feat(im-core): agent can route message to correct channel
  fix(agent-runtime): memory retriever handles empty result set
```

### 什么情况不强求 TDD

- **探索性开发** (Spike): 不确定技术方案时，先写可丢弃的验证代码
- **UI 布局调试**: CSS/Tailwind 的视觉调整
- **第三方集成调试**: 调试 OpenClaw API 的响应格式时先搞清楚对方返回什么

**但是**: Spike 结束后，正式实现必须补测试。

---

## 测试文件组织规范

```
server/im-core/
├── internal/
│   ├── handler/
│   │   ├── message_handler.go
│   │   └── message_handler_test.go      # 同目录，_test.go 后缀
│   ├── service/
│   │   ├── channel_service.go
│   │   └── channel_service_test.go
│   └── domain/
│       ├── agent_state.go
│       └── agent_state_test.go
└── test/                                 # 集成测试 (用 build tag)
    ├── integration_test.go               # //go:build integration
    └── testhelper/
        └── db.go

server/agent-runtime/
├── src/
│   ├── soul_engine/
│   │   ├── profile.py
│   │   └── test_profile.py              # 单元测试与源码同目录
│   └── connector/
│       ├── base.py
│       └── test_base.py
└── tests/                                # 集成测试独立目录
    ├── conftest.py
    └── test_agent_lifecycle.py

client/web/
└── src/
    ├── components/
    │   └── ChatMessage/
    │       ├── ChatMessage.tsx
    │       └── ChatMessage.test.tsx      # 组件测试同目录
    └── stores/
        ├── chatStore.ts
        └── chatStore.test.ts
```

---

## Go 测试规范

### 工具链

| 工具 | 用途 |
|------|------|
| `testing` (标准库) | 测试框架 |
| `testify/assert` | 断言 |
| `testify/mock` | Mock 对象 |
| `testify/suite` | 测试套件（集成测试用） |
| `sqlmock` | SQL Mock |
| `httptest` | HTTP Handler 测试 |
| `go test -race` | 竞态检测（必须开启） |

### Table-Driven Test 模板

```go
func TestChannelService_AddMember(t *testing.T) {
    tests := []struct {
        name        string
        channelType string
        memberRole  string
        wantErr     bool
        errContains string
    }{
        {
            name:        "admin can add member to public channel",
            channelType: "public",
            memberRole:  "admin",
            wantErr:     false,
        },
        {
            name:        "guest cannot add member to private channel",
            channelType: "private",
            memberRole:  "guest",
            wantErr:     true,
            errContains: "permission denied",
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            svc := NewChannelService(/* mock deps */)
            err := svc.AddMember(ctx, channelID, userID, tt.memberRole)
            if tt.wantErr {
                require.Error(t, err)
                assert.Contains(t, err.Error(), tt.errContains)
            } else {
                assert.NoError(t, err)
            }
        })
    }
}
```

### Mock 规范

```go
// 定义接口而非具体类型
type MessageRepository interface {
    Save(ctx context.Context, msg *Message) error
    FindByChannel(ctx context.Context, channelID string, limit int) ([]Message, error)
}

// 在测试中用 testify/mock 生成 Mock
type MockMessageRepo struct {
    mock.Mock
}

func (m *MockMessageRepo) Save(ctx context.Context, msg *Message) error {
    args := m.Called(ctx, msg)
    return args.Error(0)
}
```

### 运行命令

```bash
# 单元测试 (快速)
go test ./internal/... -short -count=1

# 含竞态检测
go test ./internal/... -race -count=1

# 集成测试
go test ./test/... -tags=integration -count=1

# 覆盖率报告
go test ./... -coverprofile=coverage.out
go tool cover -html=coverage.out
```

### 覆盖率要求

| 层级 | 最低行覆盖率 |
|------|-------------|
| domain 逻辑 | 90% |
| service 层 | 80% |
| handler 层 | 70% |
| 全项目 | 75% |

---

## Python 测试规范

### 工具链

| 工具 | 用途 |
|------|------|
| `pytest` | 测试运行器 |
| `pytest-asyncio` | 异步测试支持 |
| `pytest-mock` | Mock 对象 |
| `pytest-cov` | 覆盖率报告 |
| `factory_boy` | 测试数据工厂 |
| `httpx` + `respx` | HTTP Mock |
| `freezegun` | 时间冻结 |

### 测试模板

```python
import pytest
from soul_engine.profile import SoulProfile, Persona

class TestSoulProfile:
    """Soul Profile 单元测试"""

    def test_assemble_prompt_injects_persona_traits(self):
        """验证人格特质被正确注入到 System Prompt 中"""
        profile = SoulProfile(
            name="陈思远",
            persona=Persona(openness=0.75, directness=0.80),
        )
        prompt = profile.build_system_prompt(context={}, memories=[])

        assert "陈思远" in prompt
        assert "直接" in prompt or "direct" in prompt.lower()

    @pytest.mark.parametrize("trait_value,expected_keyword", [
        (0.1, "谨慎"),
        (0.5, "平衡"),
        (0.9, "激进"),
    ])
    def test_risk_tolerance_affects_decision_prompt(
        self, trait_value, expected_keyword
    ):
        """验证风险偏好值映射到正确的提示词"""
        persona = Persona(risk_tolerance=trait_value)
        prompt = persona.render_decision_guidance()

        assert expected_keyword in prompt

    def test_red_line_violation_raises_flag(self):
        """验证触碰红线时正确标记"""
        profile = SoulProfile(
            name="Agent",
            red_lines=["不能修改生产数据库"],
        )
        action = {"type": "db_write", "target": "production"}

        violations = profile.check_red_lines(action)
        assert len(violations) == 1
```

### Fixtures 规范

```python
# tests/conftest.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

@pytest.fixture
async def db_session():
    """创建测试数据库会话，测试后回滚"""
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost:5432/test")
    async with engine.begin() as conn:
        async with AsyncSession(conn) as session:
            yield session
            await conn.rollback()

@pytest.fixture
def sample_agent_profile():
    """标准测试用 Agent 配置"""
    return {
        "name": "测试Agent",
        "role": "测试工程师",
        "persona": {
            "openness": 0.5,
            "conscientiousness": 0.9,
            "extraversion": 0.3,
            "agreeableness": 0.7,
            "neuroticism": 0.2,
        },
        "values": {
            "core_principles": ["质量优先"],
            "red_lines": ["不能跳过测试直接上线"],
        },
    }

@pytest.fixture
def mock_llm_response(mocker):
    """Mock LLM API 返回"""
    return mocker.patch(
        "anthropic.AsyncAnthropic.messages.create",
        return_value=MagicMock(content=[TextBlock(text="Mocked reply")]),
    )
```

### Agent 推理测试的特殊处理

LLM 输出是非确定性的，因此对 Agent 推理的测试采用"契约断言"而非"精确断言"：

```python
class TestAgentReasoning:
    """Agent 推理测试 —— 不测具体回复内容，测回复契约"""

    async def test_agent_response_is_non_empty(self, agent, context):
        """Agent 必须产生非空回复"""
        thought = await agent.think(context, memory=[])
        assert len(thought.text) > 0

    async def test_agent_response_mentions_named_entities(self, agent, context):
        """提到具体人名时，回复应包含该人名"""
        context.messages.append({"text": "@陈思远 你觉得这个方案怎么样？"})
        thought = await agent.think(context, memory=[])

        assert "陈思远" in thought.text or "思远" in thought.text

    async def test_agent_respects_red_lines(self, agent_with_strict_rules, context):
        """Agent 不应建议违反红线的行为"""
        context.messages.append({
            "text": "我们直接改生产数据库吧，反正现在用户少"
        })
        thought = await agent_with_strict_rules.think(context, memory=[])

        # 回复应拒绝或表示需要审批
        reject_keywords = ["不能", "不可", "需要审批", "生产环境", "risk"]
        assert any(kw in thought.text for kw in reject_keywords)

    async def test_agent_calls_appropriate_tool(self, agent, context):
        """当需要数据时，Agent 应调用查询工具而非瞎编"""
        context.messages.append({
            "text": "最近一周的新增用户有多少？"
        })
        thought = await agent.think(context, memory=[])

        # Agent 应该尝试执行数据查询工具
        tool_names = [a.get("tool") for a in thought.actions]
        assert "query_database" in tool_names or "run_sql" in tool_names
```

### 运行命令

```bash
# 单元测试 (快速，不调 LLM)
pytest src/ -x -v --timeout=5

# 集成测试
pytest tests/ -x -v -m integration

# 覆盖率
pytest --cov=src --cov-report=html --cov-report=term

# 跳过 LLM 调用测试
pytest -m "not llm"
```

### 覆盖率要求

| 层级 | 最低行覆盖率 |
|------|-------------|
| Soul Engine 核心逻辑 | 90% |
| Connector 适配层 | 85% |
| Memory 系统 | 85% |
| Agent Runtime 整体 | 75% |

---

## 前端测试规范

### 工具链

| 工具 | 用途 |
|------|------|
| `vitest` | 测试运行器 |
| `@testing-library/react` | 组件测试 |
| `@testing-library/user-event` | 用户交互模拟 |
| `msw` | API Mock |
| `jsdom` | DOM 环境 |

### 测试范围

前端仅对**业务逻辑层**进行 TDD:
- Zustand stores (reducer 逻辑、状态转换)
- 工具函数 (日期格式化、权限判断、消息预处理)
- 自定义 Hooks (不含 DOM 交互的纯逻辑)

组件 UI 外观不做自动化测试，用 Storybook 做人工展示。

---

## CI 流水线

```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]

jobs:
  unit-go:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.22" }
      - run: go test ./internal/... -race -count=1 -short
        working-directory: server/im-core
      - run: go test ./internal/... -race -count=1 -short
        working-directory: server/api-gateway

  unit-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[test]"
        working-directory: server/agent-runtime
      - run: pytest src/ -x -m "not llm" --cov --cov-fail-under=75

  integration:
    needs: [unit-go, unit-python]
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_PASSWORD: test }
    steps:
      - uses: actions/checkout@v4
      - run: go test ./test/... -tags=integration
        working-directory: server/im-core
      - run: pytest tests/ -m integration
        working-directory: server/agent-runtime
```

---

## 日常开发命令速查

```bash
# 运行全项目测试 (排除 LLM 调用)
bash scripts/test-all.sh

# 运行全项目测试 (含 LLM 调用)
bash scripts/test-all.sh --include-llm

# 仅运行变更文件相关的测试
bash scripts/test-changed.sh

# 生成全项目覆盖率报告
bash scripts/coverage.sh
```

## Git Hooks (pre-commit)

```bash
# .githooks/pre-commit — 提交前自动跑变更相关的测试
#!/bin/bash
# 获取变更文件
changed=$(git diff --cached --name-only --diff-filter=ACM)

if echo "$changed" | grep -q "server/im-core"; then
    echo "Running Go unit tests..."
    cd server/im-core && go test ./internal/... -short -count=1 || exit 1
fi

if echo "$changed" | grep -q "server/agent-runtime/src"; then
    echo "Running Python unit tests..."
    cd server/agent-runtime && pytest src/ -x -q --timeout=5 || exit 1
fi
```
