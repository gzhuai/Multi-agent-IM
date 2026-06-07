import { useState } from "react";
import { useAgentStore } from "../../stores/agentStore";
import { useChatStore } from "../../stores/chatStore";
import { useAuthStore } from "../../stores/authStore";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ChannelCreateDialog({ open, onClose }: Props) {
  const [name, setName] = useState("");
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());
  const agents = useAgentStore((s) => s.agents);
  const addChannel = useChatStore((s) => s.addChannel);
  const userId = useAuthStore((s) => s.userId);

  if (!open) return null;

  const toggleAgent = (id: string) => {
    const next = new Set(selectedAgents);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedAgents(next);
  };

  const handleCreate = async () => {
    if (!name.trim()) return;

    const members = Array.from(selectedAgents).map((id) => ({
      id,
      type: "agent",
      role: "member",
    }));

    try {
      const resp = await fetch("/api/channels", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-User-ID": userId || "dev-user-1",
        },
        body: JSON.stringify({
          name: name.trim(),
          organization_id: "default",
          members,
        }),
      });

      if (resp.ok) {
        const channel = await resp.json();
        addChannel({
          id: channel.id,
          name: channel.name,
          type: "group",
          isAgentChannel: true,
        });
        onClose();
        setName("");
        setSelectedAgents(new Set());
      }
    } catch (err) {
      console.error("Failed to create channel:", err);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-surface-dark rounded-xl w-[420px] shadow-2xl border border-white/10">
        {/* Header */}
        <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
          <h2 className="text-white font-semibold text-[15px]">创建群组频道</h2>
          <button
            onClick={onClose}
            className="text-surface-muted hover:text-white transition-colors text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="text-[13px] text-surface-muted block mb-1.5">
              频道名称
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：产品需求讨论"
              className="w-full px-3 py-2 rounded-lg bg-surface-darker border border-white/10 text-white text-[13px] placeholder:text-surface-muted/50 focus:outline-none focus:border-brand-500/50"
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              autoFocus
            />
          </div>

          <div>
            <label className="text-[13px] text-surface-muted block mb-1.5">
              选择 AI 员工 ({selectedAgents.size} 个已选)
            </label>
            <div className="max-h-[200px] overflow-y-auto space-y-1">
              {agents.length === 0 && (
                <p className="text-surface-muted text-xs py-2">
                  暂无可用的 AI 员工，请先在「AI 员工管理」中创建
                </p>
              )}
              {agents
                .filter((a) => a.status !== "OFFLINE")
                .map((agent) => {
                  const isSelected = selectedAgents.has(agent.id);
                  return (
                    <button
                      key={agent.id}
                      onClick={() => toggleAgent(agent.id)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all ${
                        isSelected
                          ? "bg-brand-500/20 border border-brand-500/30 text-white"
                          : "bg-surface-darker border border-transparent text-surface-muted hover:bg-white/5"
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors ${
                          isSelected
                            ? "border-brand-400 bg-brand-500"
                            : "border-white/20"
                        }`}
                      >
                        {isSelected && (
                          <svg
                            width="10"
                            height="10"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="white"
                            strokeWidth="3"
                          >
                            <path d="M20 6L9 17l-5-5" />
                          </svg>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium truncate">
                          {agent.displayName}
                        </div>
                        <div className="text-[11px] text-surface-muted/60">
                          {agent.role} · {agent.status}
                        </div>
                      </div>
                    </button>
                  );
                })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-white/5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-[13px] text-surface-muted hover:text-white hover:bg-white/5 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={!name.trim() || selectedAgents.size === 0}
            className="px-5 py-2 rounded-lg text-[13px] font-medium bg-brand-500 text-white hover:bg-brand-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            创建频道
          </button>
        </div>
      </div>
    </div>
  );
}
