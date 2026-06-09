# Phase -1 前置研究报告

> 验证外部 Agent 框架的实际可用性及 API 形态
> 研究日期：2026-06-09

---

## 执行摘要

| 框架 | 真实存在? | API 可编程调用? | 集成价值 | 建议 |
|:-----|:---------|:---------------|:--------|:-----|
| **Anthropic API** (原 "Claude Code") | ✅ 确定 | ✅ `anthropic` Python SDK | **最高** | Phase 2 实施，改名 "Anthropic Agent Connector" |
| **OpenClaw** | ✅ 确定 | ⚠️ 是竞品平台，非嵌入式框架 | **重新评估** | 不适合作为"大脑框架"嵌入 |
| **Hermes Agent** (NousResearch) | ✅ 确定 | ✅ `from run_agent import AIAgent` | **高** | Phase 4 可行，确认可嵌入式集成 |

---

## 一、Anthropic API（原计划中的 "Claude Code Connector"）

### 1.1 关键发现：名称需要纠正

**"Claude Code" 是 Anthropic 的 CLI 产品，不是一个可供程序调用的 SDK 或库。** 我们无法"集成 Claude Code"——我们只能用 Anthropic API。

现有代码中的 `ClaudeCodeConnector` 实际上已经是正确的做法：用 `anthropic.AsyncAnthropic` SDK 直接调 API，自己实现 tool_use 循环。

### 1.2 API 能力清单

| 能力 | 支持 | 详情 |
|:-----|:----:|:-----|
| 文本生成 | ✅ | streaming + non-streaming |
| 工具调用 | ✅ | tool_use + tool_result 循环 |
| 并行工具调用 | ✅ | Claude 4 默认并行，一次返回多个 tool_use block |
| 工具数量上限 | ⚠️ 无硬限制 | 实践建议 ≤20 个工具定义（超过后性能下降） |
| Prompt Caching | ✅ | System prompt 可标记 cache_control breakpoint |
| 流式 + 工具 | ✅ | 三个阶段：text_delta → input_json_delta → tool_result |
| Thinking/推理 | ✅ | 扩展思考（sonnet/opus 支持） |
| 最大上下文 | ✅ | 200K tokens |
| 计算机操作 | ✅ | computer_use 工具（Beta） |

### 1.3 Agent Loop 模式（已验证可用）

```
1. anthropic.messages.create(system=..., messages=..., tools=...)
2. 检查 stop_reason:
   - "end_turn" → 返回 final text
   - "tool_use"  → 执行工具，追加 tool_result，回到步骤 1
   - "max_tokens" → 增加 max_tokens 重试
3. 循环直到 end_turn 或达到 MAX_ROUNDS
```

### 1.4 结论

- **名称修正**：`claude_code` connector → `anthropic_agent` connector
- **技术方案**：Anthropic Python SDK (`anthropic`) + 自建工具循环
- **工期评估**：7-10 天（工具集 12 个 + 沙箱 + 审批流 + 流式事件）
- **风险**：无。Anthropic API 是成熟的商业化产品。
- **依赖**：`anthropic` Python 包（已有）+ `ANTHROPIC_API_KEY`（需配置）

---

## 二、OpenClaw

### 2.1 项目信息

| 项目 | 详情 |
|:-----|:-----|
| GitHub | `openclaw/openclaw` |
| 语言 | Node.js / TypeScript |
| 定位 | **AI Agent 网关 / 即时通讯平台** |
| 历史 | 2025 年启动 → 2026年1月更名为 OpenClaw |
| 官网 | docs.openclaw.ai |

### 2.2 核心发现：OpenClaw 是竞品，不是"大脑框架"

OpenClaw 的定位与 Multi-agent-IM **高度重叠**：

```
Multi-agent-IM:     IM平台 ←→ Agent Runtime ←→ 外部框架
OpenClaw:           IM平台 ←→ Agent Gateway ←→ 外部框架(ACP)
                     ↑ 同样的定位          ↑
```

两者都是：
- 连接多个消息渠道（Telegram/Discord/Slack 等）的网关
- Agent 生命周期管理
- 多 Agent 协作编排
- 子 Agent 生成与会话管理

**OpenClaw 不是一个你可以 `pip install` 或 `import` 的 Python 库**——它是一个独立的 Node.js 服务，有自己的消息网关、自己的配置系统、自己的插件生态。

### 2.3 ACP 协议（值得关注）

OpenClaw 的 ACP（Agent Control Protocol）是一个标准化协议，用于 spawn 外部编码工具（Claude Code、Gemini CLI、Codex 等）：

```json
// sessions_spawn 工具调用
{
  "task": "Research this codebase for auth patterns",
  "runtime": "acp",
  "agentId": "claude",
  "mode": "run",
  "cwd": "/home/user/project"
}
```

支持的 ACP harness：`claude`, `codex`, `copilot`, `cursor`, `droid`, `gemini`, `kilocode`, `qwen` 等 12+ 种。

### 2.4 重新评估集成策略

| 原计划 | 修正后 |
|:-------|:-------|
| OpenClaw 作为 Agent 的"大脑框架"嵌入 | ❌ 架构不合理（平台嵌平台） |
| 实现 OpenClaw Connector（Phase 3） | ❌ 取消 |

**替代方案**：

| 方案 | 说明 |
|:-----|:-----|
| **A. 自建多 Agent 编排** | 在 Agent Runtime 内实现轻量 DAG 工作流引擎，不依赖外部框架 |
| **B. 参考 ACP 协议** | 实现 ACP-compatible 的 agent spawn 接口，让 Multi-agent-IM 可以 spawn 外部 CLI agent |
| **C. 使用 CrewAI / AutoGen** | 用已有的 Python 多 Agent 框架替代 OpenClaw 的角色 |

**推荐方案 B + A**：
- 短期（Phase 3 替代）：在 Agent Runtime 内建一个轻量的 `WorkflowEngine`，支持 DAG 任务编排
- 中期：实现 ACP 兼容接口，让 Multi-agent-IM 可以 spawn Claude Code / Codex CLI 等

### 2.5 结论

- **原计划 Phase 3（OpenClaw Connector）取消**
- **替换为**：自建轻量 WorkflowEngine（DAG编排 + 子Agent委派）
- **中期规划**：ACP 协议兼容层
- **节省工期**：原 5-7 天 → 新 4-5 天（WorkflowEngine）

---

## 三、Hermes Agent（NousResearch）

### 3.1 项目信息

| 项目 | 详情 |
|:-----|:-----|
| GitHub | `NousResearch/hermes-agent` |
| 语言 | Python |
| 安装 | `pip install git+https://github.com/NousResearch/hermes-agent.git` |
| 定位 | **全功能 AI Agent 框架**（不是平台，是嵌入式框架） |
| 版本 | v0.15.x（2026年6月） |
| 许可 | 开源 |

### 3.2 编程接口验证

```python
from run_agent import AIAgent

# 基础用法
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    quiet_mode=True,        # 必须，否则打印 CLI 进度条到 stdout
    skip_memory=True,       # 推荐，用我们自己的记忆系统
    enabled_toolsets=["web_search", "read_file", "terminal"],
)

# 单轮对话
response = agent.chat("What is the capital of France?")

# 多轮对话（完整消息历史）
result = agent.run_conversation(
    user_message="Search for recent Python features",
    task_id="task-1",
)
# result["final_response"]   → Agent 最终回复
# result["messages"]         → 完整消息历史
```

### 3.3 核心能力

| 能力 | 支持 | 详情 |
|:-----|:----:|:-----|
| 工具集 | ✅ | 70+ 工具，28+ 工具集 |
| 文件操作 | ✅ | read_file, write_file, patch, search_files |
| Shell 执行 | ✅ | 6 种后端（本地/Docker/SSH/Daytona/Modal/Singularity） |
| 子 Agent 委派 | ✅ | `delegate_task` 工具（共享迭代预算） |
| Web 搜索 | ✅ | web_search, web_extract |
| 浏览器自动化 | ✅ | 10 个 Playwright 工具 |
| 代码执行 | ✅ | 沙箱 `execute_code` |
| 多 LLM 提供商 | ✅ | 18+ 提供商（OpenAI/Anthropic/DeepSeek/OpenRouter 等） |
| Prompt Caching | ✅ | Anthropic prompt caching |
| 上下文压缩 | ✅ | ContextCompressor（token 超限自动摘要对话历史） |
| 记忆系统 | ✅ | SQLite + FTS5 |
| 循环中断保护 | ✅ | IterationBudget（默认 90 轮）+ 熔断器 |

### 3.4 集成方式

集成到 Multi-agent-IM Agent Runtime：

```python
# 在 HermesConnector 中
from run_agent import AIAgent

class HermesConnector(AgentConnector):
    async def act(self, context, soul_profile, memory_context, event_callback):
        # 1. 构建 Hermes-compatible 配置
        agent = AIAgent(
            model=soul_profile.identity.llm_model or "anthropic/claude-sonnet-4",
            quiet_mode=True,
            skip_memory=True,              # 使用我们的 MemoryService
            enabled_toolsets=[...],        # 根据 agent 权限配置
            system_message=soul_profile.build_system_prompt(...),
        )

        # 2. 执行对话
        result = agent.run_conversation(
            user_message=context.messages[-1]["content"],
            conversation_history=self._adapt_history(context.messages[:-1]),
        )

        # 3. 转换结果
        return ActionResult(
            text=result["final_response"],
            ...
        )
```

### 3.5 注意事项

| 问题 | 应对 |
|:-----|:-----|
| AIAgent 非线程安全 | 每个请求创建新实例（轻量，无副作用） |
| 有自己的记忆系统 | 设置 `skip_memory=True`，使用我们的 MemoryService |
| 默认 CLI 输出 | 设置 `quiet_mode=True` |
| 默认加载 AGENTS.md | 设置 `skip_context_files=True` |
| 同步 API（非 async） | 用 `asyncio.to_thread()` 包装 |

### 3.6 结论

- **Hermes Agent 完全可用作嵌入式 Python 库** ✅
- **Phase 4 可行**，但需要调整集成方式（包装 AIAgent 而非调 REST API）
- **工期评估**：原 3-5 天 → **5-7 天**（含 AIAgent 包装 + 异步桥接 + 权限控制 + 测试）

---

## 四、对迁移计划的修正建议

### 4.1 框架列表修正

```
原计划                          修正后
────────────────────────────────────────────────────
Phase 2: Claude Code Connector   Phase 2: Anthropic Agent Connector
                                 (Anthropic API + 自建工具循环)

Phase 3: OpenClaw Connector      Phase 3: 取消
                                 → Phase 3: WorkflowEngine (自建)
                                 (轻量 DAG 编排 + 子Agent委派)

Phase 4: Hermes Connector        Phase 4: Hermes Agent Connector
                                 (import AIAgent, 包装为 Connector)
                                 ↓ 工期 +2天（需处理同步/异步桥接）
```

### 4.2 新增候选框架

| 框架 | 定位 | 优先级 |
|:-----|:-----|:------|
| **CrewAI** | Python 多 Agent 编排框架 | 可替代 Phase 3（如果 WorkflowEngine 不够用） |
| **AutoGen** (Microsoft) | 多 Agent 对话框架 | 备用 |
| **LangGraph** | 有状态 Agent 工作流 | 备用 |

这些不作为当前 Phase 的必选项，但留有扩展空间。

### 4.3 工期修正

| 阶段 | 原计划 | 修正后 | 原因 |
|:-----|:------|:------|:-----|
| Phase -1 | 2-3天 | ✅ 完成 | 研究已产出 |
| Phase 0 | 3-4天 | 不变 | |
| Phase 1 | 4-5天 | 不变 | |
| Phase 2 | 7-10天 | 不变 | Anthropic Agent |
| Phase 3 | 5-7天 | **4-5天** | 改为自建 WorkflowEngine |
| Phase 4 | 3-5天 | **5-7天** | Hermes AIAgent 包装更复杂 |
| Phase 5 | 4-6天 | 不变 | |
| **总计** | 6-8周 | **6-8周** | 不变 |

---

## 五、结论

1. **OpenClaw 的重大发现**：它是竞品平台而非嵌入式框架。原计划中"OpenClaw 作为 Agent 大脑"的假设是错误的。需要将 Phase 3 改为自建 WorkflowEngine。

2. **Hermes Agent 确认可用**：`from run_agent import AIAgent` 直接可用，是真正的 Python 嵌入式 Agent 框架。需要处理同步/异步桥接和 CLI 输出抑制。

3. **Anthropic API 成熟稳定**：改名纠正即可，技术方案不变。

4. **Multi-agent-IM 的独特性更加明确**：市面上 OpenClaw 是唯一接近的竞品（AI 网关 + IM），但它不支持嵌入式 Hermes Agent 或 Anthropic API 工具循环——这正是 Multi-agent-IM 的差异化空间。

---

*Phase -1 研究完成。可以进入 Phase 0（定义目标架构与接口冻结）。*
