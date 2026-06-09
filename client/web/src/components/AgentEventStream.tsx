/**
 * AgentEventStream — 实时展示 Agent 执行过程中的状态变化。
 *
 * 监听 WebSocket 推送的 agent_event 消息，渲染:
 *   - THINKING: "思考中..." 动画条
 *   - TOOL_EXECUTING: "🔧 正在执行 {tool_name}"
 *   - TOOL_RESULT: "✅ / ❌ {tool_name} 完成"
 *   - APPROVAL_NEEDED: 审批卡片
 *   - AGENT_DONE: 完成状态
 */

import { useEffect, useState } from "react";

type AgentEvent = {
  agent_id: string;
  agent_name: string;
  event: string;
  task_id?: string;
  payload?: Record<string, unknown>;
  ts?: number;
};

type EventEntry = {
  id: string;
  event: AgentEvent;
  dismissed: boolean;
};

const eventIcons: Record<string, string> = {
  agent_started: "🚀",
  thinking: "💭",
  thought_chunk: "",
  reasoning: "🧠",
  tool_executing: "🔧",
  tool_result: "✅",
  tool_error: "❌",
  approval_needed: "🛡️",
  approval_granted: "✅",
  approval_denied: "❌",
  approval_timeout: "⏰",
  progress: "📊",
  agent_done: "🏁",
  agent_error: "💥",
};

const eventLabels: Record<string, string> = {
  agent_started: "开始执行",
  thinking: "思考中...",
  tool_executing: "执行工具",
  tool_result: "工具完成",
  tool_error: "工具出错",
  approval_needed: "需要审批",
  approval_granted: "审批通过",
  approval_denied: "审批被拒",
  agent_done: "完成",
  agent_error: "出错",
};

export function AgentEventStream({ channelId }: { channelId?: string }) {
  const [events, setEvents] = useState<EventEntry[]>([]);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    // Listen for agent events from the chat store
    // In production, this connects to WebSocket
    const handler = (e: CustomEvent<AgentEvent>) => {
      const evt = e.detail;
      if (channelId && evt.payload?.channel_id && evt.payload.channel_id !== channelId) {
        return; // filter by channel
      }
      setEvents((prev) => {
        // Keep last 20, auto-dismiss agent_done after 5s
        const entry: EventEntry = {
          id: `${evt.agent_id}-${evt.ts || Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          event: evt,
          dismissed: false,
        };
        const next = [entry, ...prev].slice(0, 20);

        // Auto-dismiss done events after 5s
        if (evt.event === "agent_done" || evt.event === "agent_error") {
          setTimeout(() => {
            setEvents((cur) =>
              cur.map((e) => (e.id === entry.id ? { ...e, dismissed: true } : e))
            );
          }, 5000);
        }

        return next;
      });
    };

    window.addEventListener("agent-event", handler as EventListener);
    return () => window.removeEventListener("agent-event", handler as EventListener);
  }, [channelId]);

  const visibleEvents = events.filter((e) => !e.dismissed);

  if (visibleEvents.length === 0) return null;

  return (
    <div className="border-b border-surface-700 bg-surface-850">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2 flex items-center justify-between text-xs text-surface-400 hover:text-surface-300 transition-colors"
      >
        <span>🤖 Agent 实时状态 ({visibleEvents.length})</span>
        <span className="text-[10px]">{expanded ? "收起 ▲" : "展开 ▼"}</span>
      </button>

      {/* Event list */}
      {expanded && (
        <div className="px-4 pb-2 space-y-1 max-h-40 overflow-y-auto">
          {visibleEvents.slice(0, 8).map((entry) => {
            const { event } = entry;
            const icon = eventIcons[event.event] || "•";
            const label = eventLabels[event.event] || event.event;
            const toolName = (event.payload?.tool_name as string) || "";
            const summary = (event.payload?.summary as string) || "";
            const error = (event.payload?.error as string) || "";

            const isError = event.event === "tool_error" || event.event === "agent_error";
            const isDone = event.event === "agent_done";
            const isApproval = event.event === "approval_needed";

            return (
              <div
                key={entry.id}
                className={`flex items-start gap-2 text-xs py-0.5 ${
                  isError ? "text-accent-rose" : isDone ? "text-accent-green" : "text-surface-300"
                } ${isApproval ? "bg-amber-500/10 rounded px-2 py-1" : ""}`}
              >
                <span className="shrink-0 mt-0.5">{icon}</span>
                <div className="flex-1 min-w-0">
                  <span className="font-medium">{event.agent_name || event.agent_id?.slice(0, 8)}</span>
                  {" · "}
                  <span>{label}</span>
                  {toolName && <span className="text-surface-500"> · {toolName}</span>}
                  {summary && (
                    <span className="text-surface-500 truncate block">
                      {summary.length > 80 ? summary.slice(0, 80) + "..." : summary}
                    </span>
                  )}
                  {error && <span className="text-accent-rose truncate block">{error.slice(0, 100)}</span>}
                </div>
                <span className="text-[10px] text-surface-500 shrink-0">
                  {event.ts ? new Date(event.ts).toLocaleTimeString().slice(0, 5) : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Helper: dispatch an agent event (called by WebSocket handler or test code).
 */
export function dispatchAgentEvent(event: AgentEvent) {
  window.dispatchEvent(new CustomEvent("agent-event", { detail: event }));
}
