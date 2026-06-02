import { useEffect, useState } from "react";
import { useAgentStore, sortAgentsByBusyness } from "../../stores/agentStore";

const agentGradients = [
  "from-brand-400 via-brand-500 to-accent-indigo",
  "from-accent-teal via-cyan-400 to-brand-500",
  "from-accent-orange via-amber-400 to-accent-rose",
  "from-accent-green via-emerald-400 to-accent-teal",
  "from-accent-purple via-violet-400 to-accent-pink",
];

const statusConfig: Record<string, { dot: string; glow: string; label: string }> = {
  OFFLINE:  { dot: "bg-surface-border", glow: "", label: "离线" },
  IDLE:     { dot: "bg-accent-green", glow: "shadow-[0_0_6px_rgba(34,197,94,0.4)]", label: "空闲" },
  THINKING: { dot: "bg-accent-amber", glow: "shadow-[0_0_8px_rgba(245,158,11,0.5)] animate-pulse", label: "思考中" },
  WORKING:  { dot: "bg-accent-amber", glow: "shadow-[0_0_8px_rgba(245,158,11,0.6)] animate-pulse", label: "工作中" },
  WAITING:  { dot: "bg-accent-orange", glow: "shadow-[0_0_6px_rgba(249,115,22,0.4)]", label: "等待中" },
  PAUSED:   { dot: "bg-accent-rose", glow: "", label: "已暂停" },
};

export function AgentPanel() {
  const agents = useAgentStore((s) => s.agents);
  const [sortedAgents, setSortedAgents] = useState(sortAgentsByBusyness(agents));

  // Re-sort when agents change (simulates real-time reordering)
  useEffect(() => {
    setSortedAgents(sortAgentsByBusyness(agents));
  }, [agents]);

  // Periodic re-sort for live feel
  useEffect(() => {
    const interval = setInterval(() => {
      const current = useAgentStore.getState().agents;
      setSortedAgents(sortAgentsByBusyness(current));
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <aside className="w-64 bg-surface-white border-l border-surface-gray flex flex-col shrink-0">
      {/* Header */}
      <div className="h-14 flex items-center px-4 border-b border-surface-gray">
        <h2 className="text-sm font-bold text-surface-dark">AI 员工</h2>
        <span className="ml-auto text-xs bg-surface-dark text-white px-2.5 py-0.5 rounded-full font-bold">
          {agents.length}
        </span>
      </div>

      {/* Agent list — sorted by busyness */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {sortedAgents.length === 0 ? (
          <div className="text-center py-16">
            <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-gradient-to-br from-brand-100 to-purple-100 flex items-center justify-center text-2xl">🤖</div>
            <p className="text-xs text-surface-muted">暂无 AI 员工</p>
          </div>
        ) : (
          sortedAgents.map((agent, idx) => {
            const status = statusConfig[agent.status];
            const grad = agentGradients[idx % agentGradients.length];
            const isBusy = agent.status === "WORKING" || agent.status === "THINKING";
            const hasActivity = agent.currentActivity && agent.currentActivity !== "";

            return (
              <div
                key={agent.id}
                className={`group p-3 rounded-2xl border transition-all duration-300 cursor-pointer bg-surface-white ${
                  isBusy
                    ? "border-amber-200/80 shadow-md shadow-amber-50"
                    : "border-surface-gray hover:border-brand-200 hover:shadow-card-hover"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className="relative shrink-0">
                    <div className={`w-10 h-10 rounded-2xl bg-gradient-to-br ${grad} flex items-center justify-center text-white text-sm font-bold shadow-md ${isBusy ? "animate-pulse" : ""}`}
                      style={isBusy ? { animationDuration: "3s" } : undefined}>
                      {agent.displayName[0]}
                    </div>
                    <div className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-[2.5px] border-surface-white ${status.dot} ${status.glow}`} />
                    {agent.taskCount > 1 && (
                      <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-surface-dark text-white text-[8px] font-bold flex items-center justify-center border-2 border-surface-white">
                        {agent.taskCount}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-bold text-surface-dark truncate">{agent.displayName}</div>
                    <div className="text-xxs text-surface-muted mt-0.5">{agent.role}</div>
                  </div>
                </div>

                {/* Current activity — task-level granularity */}
                <div className="mt-2.5 pt-2.5 border-t border-surface-gray/60">
                  {hasActivity ? (
                    <div className="flex items-start gap-1.5">
                      <span className="text-xxs shrink-0 mt-px">
                        {agent.status === "THINKING" ? "🧠" : agent.status === "WORKING" ? "⚡" : agent.status === "WAITING" ? "⏳" : "💤"}
                      </span>
                      <span className="text-xxs text-surface-dark/70 leading-relaxed line-clamp-2">
                        {agent.currentActivity}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <div className={`w-1.5 h-1.5 rounded-full ${status.dot} ${status.glow}`} />
                      <span className="text-xxs text-surface-muted">{status.label}</span>
                    </div>
                  )}

                  {/* Mini task stack indicator */}
                  {agent.taskCount > 1 && (
                    <div className="flex items-center gap-1 mt-1.5">
                      {Array.from({ length: Math.min(agent.taskCount, 5) }).map((_, i) => (
                        <div key={i}
                          className={`h-0.5 rounded-full bg-gradient-to-r ${grad}`}
                          style={{
                            width: `${Math.max(8, 24 - i * 3)}px`,
                            opacity: 1 - i * 0.15,
                          }}
                        />
                      ))}
                      {agent.taskCount > 5 && (
                        <span className="text-xxs text-surface-muted ml-0.5">+{agent.taskCount - 5}</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-surface-gray bg-gradient-to-r from-brand-50/50 to-purple-50/50">
        <p className="text-xxs text-surface-muted text-center">
          忙碌的 Agent 自动置顶
        </p>
      </div>
    </aside>
  );
}
