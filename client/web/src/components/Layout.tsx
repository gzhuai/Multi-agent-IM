import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar/Sidebar";
import { AgentPanel } from "./AgentPanel/AgentPanel";
import { useChatStore } from "../stores/chatStore";
import { useAgentStore } from "../stores/agentStore";

const DEMO_CHANNELS = [
  { id: "general", name: "🏠 总群", type: "group" as const, isAgentChannel: false },
  { id: "product", name: "📦 产品讨论", type: "department" as const, isAgentChannel: false },
  { id: "tech", name: "💻 技术交流", type: "department" as const, isAgentChannel: false },
  { id: "ai-office", name: "🤖 AI 虚拟办公室", type: "project" as const, isAgentChannel: true },
];

const DEMO_AGENTS = [
  { id: "agent-siyuan", name: "陈思远", displayName: "思远·产品", role: "高级产品经理", department: "产品部", status: "WORKING" as const, currentActivity: "正在撰写Q3产品路线图PRD", taskCount: 3, priorityTasks: 1 },
  { id: "agent-liming", name: "李明", displayName: "李明·研发", role: "资深后端工程师", department: "研发部", status: "WORKING" as const, currentActivity: "正在修复消息推送模块的WebSocket断连Bug", taskCount: 2, priorityTasks: 1 },
  { id: "agent-wanwan", name: "林婉", displayName: "林婉·数据", role: "数据分析师", department: "数据部", status: "WAITING" as const, currentActivity: "等待 @Simon 确认数据口径定义", taskCount: 1, priorityTasks: 0 },
];

export function Layout() {
  const channels = useChatStore((s) => s.channels);
  const agents = useAgentStore((s) => s.agents);

  useEffect(() => {
    if (channels.length === 0) {
      useChatStore.setState({ channels: DEMO_CHANNELS, activeChannelId: "general" });
    }
    if (agents.length === 0) {
      useAgentStore.setState({ agents: DEMO_AGENTS });
    }
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-surface-light">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 bg-surface-white">
        <Outlet />
      </main>
      <AgentPanel />
    </div>
  );
}
