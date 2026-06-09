import { useParams } from "react-router-dom";
import { useChatStore } from "../../stores/chatStore";
import { AgentEventStream } from "../AgentEventStream";

export function ChatArea() {
  const { channelId } = useParams();
  const messages = useChatStore((s) =>
    channelId ? s.messages[channelId] || [] : []
  );

  return (
    <div className="flex-1 flex flex-col">
      {/* Channel header */}
      <div className="h-14 flex items-center px-4 border-b border-surface-700 bg-surface-800">
        <h2 className="font-semibold text-surface-200">
          {channelId ? `# ${channelId}` : "欢迎"}
        </h2>
      </div>

      {/* v2: Agent Event Stream — 实时显示 Agent 执行状态 */}
      <AgentEventStream channelId={channelId} />

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-surface-500">
            <div className="text-center">
              <p className="text-lg mb-2">Multi-agent-IM</p>
              <p className="text-sm">
                Phase 0 脚手架已就绪。
                <br />
                Phase 1 将实现实时消息功能。
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className="flex gap-3">
              <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-xs font-bold shrink-0">
                {msg.senderName[0]}
              </div>
              <div>
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold text-sm text-surface-200">
                    {msg.senderName}
                  </span>
                  <span className="text-xs text-surface-500">
                    {msg.senderType === "agent" ? "🤖 AI" : ""}
                  </span>
                </div>
                <p className="text-surface-300 text-sm mt-0.5">{msg.content}</p>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Input area (placeholder) */}
      <div className="h-16 flex items-center px-4 border-t border-surface-700 bg-surface-800">
        <input
          type="text"
          placeholder="消息功能将在 Phase 1 实现..."
          disabled
          className="flex-1 bg-surface-700 text-surface-300 rounded-lg px-4 py-2 text-sm outline-none disabled:opacity-50"
        />
      </div>
    </div>
  );
}
