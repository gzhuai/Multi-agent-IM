import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useChatStore } from "../../stores/chatStore";
import { useAgentStore, sortAgentsByBusyness } from "../../stores/agentStore";
import { useAuthStore } from "../../stores/authStore";
import { ChannelCreateDialog } from "../ChannelCreateDialog";

const agentGradients = [
  "from-brand-400 via-brand-500 to-accent-indigo",
  "from-accent-teal via-cyan-400 to-brand-500",
  "from-accent-orange via-amber-400 to-accent-rose",
  "from-accent-green via-emerald-400 to-accent-teal",
  "from-accent-purple via-violet-400 to-accent-pink",
];

const busynessDots: Record<string, string> = {
  WORKING:  "bg-accent-amber shadow-[0_0_6px_rgba(245,158,11,0.5)]",
  THINKING: "bg-accent-amber shadow-[0_0_6px_rgba(245,158,11,0.3)] animate-pulse",
  WAITING:  "bg-accent-orange shadow-[0_0_4px_rgba(249,115,22,0.3)]",
  IDLE:     "bg-accent-green",
  PAUSED:   "bg-accent-rose",
  OFFLINE:  "bg-surface-border",
};

export function Sidebar() {
  const { channelId } = useParams();
  const channels = useChatStore((s) => s.channels);
  const agents = useAgentStore((s) => s.agents);
  const displayName = useAuthStore((s) => s.displayName);
  const activeChannel = channelId || "general";
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  const sortedAgents = sortAgentsByBusyness(agents);

  return (
    <aside className="w-64 bg-surface-dark flex flex-col shrink-0">
      {/* Logo */}
      <div className="h-14 flex items-center px-4 gap-2.5 bg-gradient-to-r from-surface-darker to-surface-dark border-b border-white/5">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-400 to-accent-purple flex items-center justify-center text-white text-sm font-bold shadow-lg shadow-brand-500/20">M</div>
        <span className="text-white font-bold text-[15px] tracking-tight">Multi-agent-IM</span>
      </div>

      {/* Search */}
      <div className="px-3 pt-3 pb-1">
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-darker text-surface-muted text-sm cursor-pointer hover:bg-white/10 transition-colors">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <span className="text-[13px]">搜索消息</span>
          <span className="ml-auto text-xxs opacity-40 text-white">⌘K</span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pt-1">
        {/* === 频道 === */}
        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="text-[11px] font-bold text-surface-muted uppercase tracking-widest">频道</span>
          <span
            className="text-surface-muted text-sm cursor-pointer hover:text-white transition-colors leading-none"
            onClick={() => setShowCreateDialog(true)}
          >
            +
          </span>
        </div>
        {channels.map((ch) => {
          const isActive = activeChannel === ch.id;
          const label = ch.name.replace(/^[^\s]+\s/, "");
          return (
            <Link
              key={ch.id}
              to={`/channel/${ch.id}`}
              className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-[13px] transition-all duration-150 mb-0.5 ${
                isActive
                  ? "bg-gradient-to-r from-brand-500/20 to-brand-500/10 text-white font-semibold shadow-sm"
                  : "text-surface-muted hover:bg-white/5 hover:text-white"
              }`}
            >
              <span className="text-base w-4 text-center shrink-0 font-medium">{ch.type === "direct" ? "@" : "#"}</span>
              <span className="truncate flex-1">{label}</span>
              {ch.id === "ai-office" && !isActive && (
                <span className="w-1.5 h-1.5 rounded-full bg-brand-400 shrink-0" />
              )}
            </Link>
          );
        })}

        <div className="border-t border-white/5 my-3 mx-3" />

        {/* === 私聊 (AI 员工) === */}
        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="text-[11px] font-bold text-surface-muted uppercase tracking-widest">私聊 · AI</span>
          <span className="text-surface-muted text-xs">{sortedAgents.length}</span>
        </div>
        {sortedAgents.map((agent, idx) => {
          const dmChannelId = `dm-${agent.id}`;
          const isActive = activeChannel === dmChannelId;
          const grad = agentGradients[idx % agentGradients.length];
          const dot = busynessDots[agent.status];

          return (
            <Link
              key={dmChannelId}
              to={`/channel/${dmChannelId}`}
              className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-[13px] transition-all duration-150 mb-0.5 group ${
                isActive
                  ? "bg-gradient-to-r from-brand-500/20 to-brand-500/10 text-white font-semibold"
                  : "text-surface-muted hover:bg-white/5 hover:text-white"
              }`}
            >
              <div className="relative shrink-0">
                <div className={`w-5 h-5 rounded-md bg-gradient-to-br ${grad} flex items-center justify-center text-white text-[9px] font-bold`}>
                  {agent.displayName[0]}
                </div>
                <div className={`absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border-[1.5px] border-surface-dark ${dot}`} />
              </div>
              <span className="truncate flex-1">{agent.displayName}</span>
              {agent.status === "WORKING" && (
                <span className="text-xxs text-accent-amber/70 shrink-0">{agent.taskCount}</span>
              )}
            </Link>
          );
        })}

        <div className="border-t border-white/5 my-3 mx-3" />

        {/* === 任务 === */}
        <Link to="/tasks"
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-[13px] text-surface-muted hover:bg-white/5 hover:text-white transition-colors">
          <span className="text-base w-4 text-center shrink-0">📋</span>
          <span>任务看板</span>
        </Link>

        {/* === 管理 === */}
        <Link to="/agents"
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-[13px] text-surface-muted hover:bg-white/5 hover:text-white transition-colors">
          <span className="text-base w-4 text-center shrink-0">🤖</span>
          <span>AI 员工管理</span>
        </Link>
      </nav>

      <ChannelCreateDialog
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
      />

      {/* User footer */}
      <div className="h-14 flex items-center gap-2.5 px-4 border-t border-white/5 bg-surface-darker/50">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-400 to-accent-purple flex items-center justify-center text-white text-xs font-bold shadow-md">
          {displayName?.[0] || "D"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] text-white font-medium truncate">{displayName || "开发者"}</div>
          <div className="text-xxs text-accent-green/80 flex items-center gap-1">
            <span className="w-1 h-1 rounded-full bg-accent-green" />在线
          </div>
        </div>
      </div>
    </aside>
  );
}
