import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "./chatStore";

describe("chatStore", () => {
  beforeEach(() => {
    useChatStore.setState({
      channels: [],
      activeChannelId: null,
      messages: {},
    });
  });

  it("should start with empty state", () => {
    const state = useChatStore.getState();
    expect(state.channels).toEqual([]);
    expect(state.activeChannelId).toBeNull();
    expect(state.messages).toEqual({});
  });

  it("should set active channel", () => {
    useChatStore.getState().setActiveChannel("ch_1");
    expect(useChatStore.getState().activeChannelId).toBe("ch_1");
  });

  it("should add messages to the correct channel", () => {
    const msg = {
      id: "msg_1",
      channelId: "ch_1",
      senderId: "user_1",
      senderType: "human" as const,
      senderName: "张三",
      content: "你好",
      timestamp: Date.now(),
    };

    useChatStore.getState().addMessage(msg);
    const messages = useChatStore.getState().messages["ch_1"];
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe("你好");
  });

  it("should load messages for a channel", () => {
    const msgs = [
      {
        id: "msg_1",
        channelId: "ch_1",
        senderId: "user_1",
        senderType: "human" as const,
        senderName: "张三",
        content: "Hello",
        timestamp: Date.now(),
      },
    ];

    useChatStore.getState().loadMessages("ch_1", msgs);
    expect(useChatStore.getState().messages["ch_1"]).toHaveLength(1);
  });
});
