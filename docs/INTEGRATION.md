# Agent框架集成规范

## 概述

Multi-agent-IM 的Agent后端是**可插拔**的。默认深度集成 Claude Code，但通过统一的 `AgentConnector` 接口，可以接入 OpenClaw、Hermes 或任何兼容的Agent框架。

```
┌──────────────────────────────────────────┐
│           Agent Runtime (Python)         │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │       Connector Registry           │  │
│  │  connector_type → Connector实例    │  │
│  └────────────┬───────────────────────┘  │
│               │                          │
│  ┌────────────┴────────────────────────┐ │
│  │      AgentConnector Interface       │ │
│  └──┬──────────┬──────────┬───────────┘ │
│     │          │          │             │
│  ┌──▼────┐ ┌──▼────┐ ┌──▼────┐        │
│  │Claude │ │Open   │ │Hermes │  ...   │
│  │ Code  │ │Claw   │ │       │        │
│  └───────┘ └───────┘ └───────┘        │
└──────────────────────────────────────────┘
```

## AgentConnector 接口规范

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

@dataclass
class ConversationContext:
    channel_id: str
    messages: list[dict]        # 最近N条消息
    participants: list[dict]    # 参与者信息
    mentioned: bool             # Agent是否被@

@dataclass
class MemorySnapshot:
    episodic: list[dict]        # 情景记忆
    semantic: list[dict]        # 语义记忆
    relational: list[dict]      # 关系记忆

@dataclass
class Thought:
    text: str                   # Agent的思考/回复文本
    actions: list[dict]         # 要执行的动作
    reasoning_trace: str        # 推理过程 (可选，用于可解释性)

@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: dict
    error: str | None

class AgentConnector(ABC):
    """Agent框架的统一抽象接口"""

    @abstractmethod
    async def initialize(self, agent_config: dict) -> None:
        """初始化连接器，传入Agent的完整配置（含soul profile）"""
        ...

    @abstractmethod
    async def think(
        self,
        context: ConversationContext,
        memory: MemorySnapshot
    ) -> Thought:
        """给定上下文和记忆，产生思考/回复"""
        ...

    @abstractmethod
    async def think_stream(
        self,
        context: ConversationContext,
        memory: MemorySnapshot
    ) -> AsyncIterator[str]:
        """流式版本：逐步产出思考内容（用于实时显示Agent正在输入）"""
        ...

    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        params: dict
    ) -> ToolResult:
        """执行指定的工具调用"""
        ...

    @abstractmethod
    def capabilities(self) -> list[str]:
        """返回该连接器支持的能力列表"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        ...
```

## Claude Code Connector

### 设计思路

Claude Code 是 Anthropic 的 CLI Agent 工具。在 Multi-agent-IM 中，我们将其封装为最优先的 Agent 后端。

两种集成方式：

**方式A: SDK直连 (推荐)**
直接使用 Claude API SDK，在 Agent Runtime 内部构建完整的 Agent 循环。这样我们可以完全控制 prompt 组装、工具调用循环和记忆注入。

**方式B: CLI封装**
将 Claude Code CLI 作为一个子进程运行，通过 stdin/stdout 与之交互。适合快速原型，但可扩展性有限。

### SDK直连架构

```python
class ClaudeCodeConnector(AgentConnector):
    """
    基于 Claude API SDK 的 Agent 连接器。

    核心循环:
    1. 组装 System Prompt (注入 Soul Profile + Memory)
    2. 发送对话上下文
    3. Claude 返回文本 + 可能的 tool_use
    4. 执行 tool_use → 将结果追加到对话
    5. 重复 3-4 直到 Claude 回复纯文本或无更多 tool_use
    6. 返回最终 Thought
    """

    def __init__(self):
        self.client = None
        self.agent_config = None
        self.tools_registry = {}  # tool_name → callable
        self.system_prompt_template = None

    async def initialize(self, agent_config: dict):
        import anthropic
        self.agent_config = agent_config
        self.client = anthropic.AsyncAnthropic(
            api_key=agent_config.get("api_key"),
            base_url=agent_config.get("base_url"),
        )
        self.system_prompt_template = self._build_system_prompt(agent_config)
        self.tools_registry = await self._load_tools(agent_config["skills"])

    async def think(self, context, memory):
        system_prompt = self._render_system_prompt(
            self.system_prompt_template, context, memory
        )

        messages = self._build_messages(context)

        # Agent Loop
        while True:
            response = await self.client.messages.create(
                model=self.agent_config.get("model", "claude-sonnet-4-6"),
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=self._get_tool_definitions(),
            )

            # 处理响应
            text_blocks = []
            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    text_blocks.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                # 没有工具调用，返回最终回复
                return Thought(
                    text="\n".join(text_blocks),
                    actions=[],
                    reasoning_trace=""
                )

            # 执行工具调用
            tool_results = []
            for tool_use in tool_uses:
                result = await self.execute_tool(
                    tool_use.name, tool_use.input
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": str(result.output) if result.success else result.error,
                    "is_error": not result.success,
                })

            # 将 assistant 消息和 tool_results 追加到对话历史
            messages.append({
                "role": "assistant",
                "content": response.content,
            })
            messages.append({
                "role": "user",
                "content": tool_results,
            })

    def _render_system_prompt(self, template, context, memory):
        """将 Soul Profile + Memory 注入 System Prompt"""
        return template.format(
            identity=self._format_identity(),
            persona=self._format_persona(),
            values=self._format_values(),
            memories=self._format_memories(memory),
            communication_reminder=self._get_communication_reminder(),
            red_lines=self._get_red_lines_reminder(),
            context=context,
        )
```

### 关键技术点

**1. Prompt Cache 优化**

Claude API 支持 Prompt Caching。Soul Profile 和工具定义变化频率低，应标记为 cache breakpoint：

```python
system_prompt = [
    {
        "type": "text",
        "text":  soul_profile_text,    # 变化少 → 标记为 cache
        "cache_control": {"type": "ephemeral"}
    },
    {
        "type": "text",
        "text":  memory_and_context,   # 变化频繁 → 不缓存
    }
]
```

**2. 工具调用循环控制**

防止 Agent 陷入无限循环：

```python
MAX_TOOL_ROUNDS = 10  # 单次think最多执行10轮工具调用
```

**3. Agent "思考中"状态流**

```
收到消息 → status: THINKING → 开始推理
       ↓
  流式输出文字 → 实时推送到IM (Agent正在输入...)
       ↓
  需要调工具 → status: WORKING (调用 {tool_name})
       ↓
  工具返回 → status: THINKING (分析工具返回结果)
       ↓
  产出最终回复 → status: IDLE
```

## OpenClaw Connector

OpenClaw 是一个开源的多Agent框架。集成方式：

```python
class OpenClawConnector(AgentConnector):
    """适配 OpenClaw 的 Agent 协议"""

    async def initialize(self, agent_config: dict):
        # OpenClaw 通过 REST API 与外部通信
        self.openclaw_endpoint = agent_config["endpoint"]
        self.openclaw_api_key = agent_config["api_key"]

    async def think(self, context, memory):
        # 将 Multi-agent-IM 的 ConversationContext 转换为 OpenClaw 的消息格式
        openclaw_payload = self._adapt_context(context, memory)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.openclaw_endpoint}/agent/think",
                json=openclaw_payload,
                headers={"Authorization": f"Bearer {self.openclaw_api_key}"}
            ) as resp:
                result = await resp.json()
                return self._adapt_response(result)
```

## Hermes Connector

Hermes 是另一个 Agent 框架，集成模式同上，通过 `AgentConnector` 接口适配。

具体实现细节将在 Phase 5 中展开，届时需要研究 Hermes 的具体 API 协议。

## 连接器选择策略

Agent 创建时指定连接器类型：

```yaml
# Agent创建请求
agent:
  name: "陈思远"
  connector:
    type: "claude_code"          # claude_code | openclaw | hermes
    config:
      model: "claude-sonnet-4-6"
      max_tokens: 4096
      temperature: 0.7
      # Claude 特定配置
      api_key_env: "ANTHROPIC_API_KEY"
      enable_thinking: true
      thinking_budget_tokens: 2000
```

也可以后续切换——Agent 的灵魂数据是独立于连接器的，换"大脑"不影响"记忆"和"人格"。

## 运行时性能考量

| 连接器 | 延迟 | 吞吐 | 成本 | 适合场景 |
|--------|------|------|------|----------|
| Claude Code (SDK) | 低 | 中 | 中 | 核心业务Agent |
| Claude Code (CLI) | 高 | 低 | 中 | 快速原型/MVP |
| OpenClaw | 中 | 中 | 低 | 内部工具Agent |
| Hermes | 中 | 中 | 低 | 特定场景Agent |

## 扩展新连接器

添加新框架只需：

1. 实现 `AgentConnector` 接口
2. 在 `connector_registry.py` 中注册
3. 在 Agent 创建界面中暴露为新选项

```python
# connector_registry.py
CONNECTOR_REGISTRY = {
    "claude_code": ClaudeCodeConnector,
    "openclaw": OpenClawConnector,
    "hermes": HermesConnector,
}

def get_connector(connector_type: str, config: dict) -> AgentConnector:
    connector_cls = CONNECTOR_REGISTRY.get(connector_type)
    if not connector_cls:
        raise ValueError(f"Unknown connector: {connector_type}")
    return connector_cls()
```
