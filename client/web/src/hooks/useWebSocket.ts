import { useEffect, useRef, useCallback } from "react";
import { useChatStore, Message } from "../stores/chatStore";
import { useAuthStore } from "../stores/authStore";
import { dispatchAgentEvent } from "../components/AgentEventStream";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const token = useAuthStore((s) => s.token);
  const addMessage = useChatStore((s) => s.addMessage);
  const loadMessages = useChatStore((s) => s.loadMessages);

  const connect = useCallback(() => {
    if (!token) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`ws://localhost:3000/ws?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case "message":
            addMessage(data.message as Message);
            break;
          case "history":
            loadMessages(data.channel_id, data.messages);
            break;
          case "pong":
            break;
          case "agent_event":
            // v2: Forward agent events to EventStream component
            dispatchAgentEvent(data);
            break;
        }
      } catch (e) {
        console.error("WebSocket message parse error:", e);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected, reconnecting in 3s...");
      setTimeout(connect, 3000);
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };
  }, [token, addMessage, loadMessages]);

  const subscribe = useCallback((channelId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "subscribe", channel_id: channelId }));
    }
  }, []);

  const sendMessage = useCallback((channelId: string, content: string, mentions?: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "message",
        channel_id: channelId,
        content,
        mentions: mentions || [],
      }));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  return { subscribe, sendMessage };
}
