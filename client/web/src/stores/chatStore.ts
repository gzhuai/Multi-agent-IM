import { create } from "zustand";

export interface Message {
  id: string;
  channelId: string;
  senderId: string;
  senderType: "human" | "agent" | "system";
  senderName: string;
  content: string;
  replyTo?: string;
  timestamp: number;
}

export interface Channel {
  id: string;
  name: string;
  type: "direct" | "group" | "department" | "project";
  isAgentChannel: boolean;
}

interface ChatState {
  channels: Channel[];
  activeChannelId: string | null;
  messages: Record<string, Message[]>;
  // Actions
  setActiveChannel: (channelId: string) => void;
  addMessage: (message: Message) => void;
  loadMessages: (channelId: string, messages: Message[]) => void;
  addChannel: (channel: Channel) => void;
  setChannels: (channels: Channel[]) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  channels: [],
  activeChannelId: null,
  messages: {},

  setActiveChannel: (channelId) => set({ activeChannelId: channelId }),

  addMessage: (message) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [message.channelId]: [
          ...(state.messages[message.channelId] || []),
          message,
        ],
      },
    })),

  loadMessages: (channelId, messages) =>
    set((state) => ({
      messages: { ...state.messages, [channelId]: messages },
    })),

  addChannel: (channel) =>
    set((state) => ({
      channels: [...state.channels, channel],
    })),

  setChannels: (channels) => set({ channels }),
}));
