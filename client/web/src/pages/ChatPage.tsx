import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useChatStore } from "../stores/chatStore";
import { useAuthStore } from "../stores/authStore";
import { useWebSocket } from "../hooks/useWebSocket";

const avatarGradients = [
  "from-brand-400 via-brand-500 to-accent-indigo",
  "from-accent-purple via-violet-500 to-accent-pink",
  "from-accent-orange via-amber-400 to-accent-rose",
  "from-accent-teal via-cyan-400 to-brand-500",
  "from-accent-green via-emerald-400 to-accent-teal",
];

const agentAvatarMap: Record<string, string> = {
  "陈思远": "from-accent-orange via-amber-400 to-accent-rose",
  "李明":   "from-accent-teal via-cyan-400 to-brand-500",
  "林婉":   "from-accent-purple via-violet-500 to-accent-pink",
};

function avatarGradient(name: string, isAgent: boolean): string {
  if (isAgent && agentAvatarMap[name]) return agentAvatarMap[name];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) % avatarGradients.length;
  return avatarGradients[Math.abs(hash)];
}

export function ChatPage() {
  const { channelId } = useParams();
  const activeChannel = channelId || "general";
  const channels = useChatStore((s) => s.channels);
  const messages = useChatStore((s) => s.messages[activeChannel] || []);
  const displayName = useAuthStore((s) => s.displayName);
  const { subscribe, sendMessage } = useWebSocket();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const channel = channels.find((c) => c.id === activeChannel);
  const channelName = channel?.name || activeChannel;

  useEffect(() => { subscribe(activeChannel); }, [activeChannel, subscribe]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendMessage(activeChannel, input.trim());
    setInput("");
  };

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Channel header — gradient bar */}
      <div className="h-14 flex items-center px-5 shrink-0 bg-gradient-to-r from-surface-white via-surface-white to-brand-50/50 border-b border-surface-gray gap-3">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-400 to-accent-purple flex items-center justify-center text-white text-xs font-bold shadow-sm">
          #
        </div>
        <div>
          <h2 className="font-semibold text-[15px] text-surface-dark leading-tight">{channelName}</h2>
          {channel?.isAgentChannel && (
            <span className="text-xxs bg-gradient-to-r from-purple-100 to-brand-100 text-brand-700 px-1.5 rounded font-medium">AI 协作</span>
          )}
        </div>
        <div className="ml-auto flex items-center gap-3 text-surface-muted text-xs">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-accent-green" />4 在线</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-0.5 bg-surface-light/60">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-5 rounded-3xl bg-gradient-to-br from-brand-100 via-purple-50 to-pink-50 flex items-center justify-center text-4xl shadow-glow">
                💬
              </div>
              <h3 className="text-surface-dark font-bold text-xl mb-2">{channelName}</h3>
              <p className="text-surface-muted text-sm">发送第一条消息，开始协作</p>
              {channel?.isAgentChannel && (
                <div className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-gradient-to-r from-purple-50 to-brand-50 text-brand-700 text-xs font-medium">
                  🤖 @AI员工 即可触发智能回复
                </div>
              )}
            </div>
          </div>
        )}

        {messages.map((msg, i) => {
          const isAgent = msg.senderType === "agent";
          const prevSame = i > 0 && messages[i - 1]?.senderId === msg.senderId;
          const grad = avatarGradient(msg.senderName, isAgent);

          return (
            <div key={msg.id} className={`flex gap-3 group ${prevSame ? "mt-0.5" : "mt-4"}`}>
              {prevSame ? (
                <div className="w-9 shrink-0" />
              ) : (
                <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${grad} flex items-center justify-center text-white text-xs font-bold shadow-md shrink-0`}>
                  {msg.senderName?.[0] || "?"}
                </div>
              )}
              <div className="min-w-0 flex-1">
                {!prevSame && (
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="font-semibold text-[13px] text-surface-dark">{msg.senderName}</span>
                    {isAgent && (
                      <span className="text-xxs bg-gradient-to-r from-purple-500/10 to-brand-500/10 text-brand-700 px-1.5 py-px rounded-full font-semibold border border-purple-200/50">AI</span>
                    )}
                    <span className="text-xxs text-surface-muted font-normal">
                      {new Date(msg.timestamp * 1000 || msg.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                )}
                <div className={`text-sm leading-relaxed ${
                  isAgent
                    ? "bg-gradient-to-r from-purple-50/80 via-blue-50/50 to-white rounded-2xl rounded-tl-md px-4 py-2.5 border border-purple-100/50"
                    : "text-surface-dark px-0.5"
                }`}>
                  <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                </div>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-5 pb-4 pt-2 bg-surface-white border-t border-surface-gray shrink-0">
        <form onSubmit={handleSend} className="flex items-end gap-2 bg-surface-light rounded-2xl border border-surface-gray focus-within:border-brand-300 focus-within:shadow-md focus-within:shadow-brand-100 transition-all px-4 py-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(e); } }}
            placeholder={`给 ${channelName} 发消息...`}
            rows={1}
            className="flex-1 bg-transparent text-sm text-surface-dark placeholder-surface-muted resize-none py-1.5 outline-none max-h-32"
          />
          <button
            type="submit"
            disabled={!input.trim()}
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-600 hover:from-brand-600 hover:to-brand-700 disabled:opacity-30 text-white transition-all shadow-md shadow-brand-500/20 disabled:shadow-none"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </form>
      </div>
    </div>
  );
}
