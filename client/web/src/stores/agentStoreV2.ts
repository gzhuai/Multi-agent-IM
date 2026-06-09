/**
 * Agent Store v2 — 框架能力追踪。
 *
 * 追踪每个 Agent 的大脑框架和能力清单，
 * 供前端展示框架对比和能力卡片。
 */

import { create } from "zustand";

// ── Capability Inventory (mirrors CapabilityInventory.to_frontend()) ──

export type FrameworkCapabilities = {
  framework: string;
  capabilities: {
    text_generation: boolean;
    streaming: boolean;
    structured_output: boolean;
  };
  filesystem: {
    read: boolean;
    write: boolean;
    delete: boolean;
    search: boolean;
  };
  execution: {
    shell: boolean;
    code: boolean;
    browser: boolean;
  };
  version_control: {
    read: boolean;
    write: boolean;
  };
  network: {
    web_search: boolean;
    web_fetch: boolean;
    api_call: boolean;
  };
  collaboration: {
    multi_agent: boolean;
    sub_agent: boolean;
    human_approval: boolean;
  };
  context: {
    max_tokens: number;
    max_output: number;
    prompt_caching: boolean;
  };
  tools: string[];
  extra?: Record<string, unknown>;
};

// Built-in framework capability presets (used when API is unavailable)
export const FRAMEWORK_PRESETS: Record<string, FrameworkCapabilities> = {
  anthropic_agent: {
    framework: "anthropic_agent",
    capabilities: { text_generation: true, streaming: true, structured_output: false },
    filesystem: { read: true, write: true, delete: false, search: true },
    execution: { shell: true, code: true, browser: false },
    version_control: { read: true, write: true },
    network: { web_search: false, web_fetch: false, api_call: false },
    collaboration: { multi_agent: false, sub_agent: false, human_approval: true },
    context: { max_tokens: 200000, max_output: 8192, prompt_caching: true },
    tools: ["read_file", "write_file", "list_files", "search_code", "shell_exec", "git_status", "git_diff", "git_branch", "git_commit", "send_message", "create_task", "update_task"],
  },
  hermes_agent: {
    framework: "hermes_agent",
    capabilities: { text_generation: true, streaming: true, structured_output: false },
    filesystem: { read: true, write: true, delete: false, search: true },
    execution: { shell: true, code: true, browser: true },
    version_control: { read: true, write: true },
    network: { web_search: true, web_fetch: true, api_call: false },
    collaboration: { multi_agent: false, sub_agent: true, human_approval: true },
    context: { max_tokens: 200000, max_output: 16384, prompt_caching: true },
    tools: ["read_file", "write_file", "patch", "search_files", "terminal", "web_search", "web_extract", "execute_code", "delegate_task", "vision_analyze"],
  },
  workflow_engine: {
    framework: "workflow_engine",
    capabilities: { text_generation: false, streaming: false, structured_output: false },
    filesystem: { read: false, write: false, delete: false, search: false },
    execution: { shell: false, code: false, browser: false },
    version_control: { read: false, write: false },
    network: { web_search: false, web_fetch: false, api_call: false },
    collaboration: { multi_agent: true, sub_agent: true, human_approval: false },
    context: { max_tokens: 0, max_output: 0, prompt_caching: false },
    tools: ["create_workflow", "cancel_workflow"],
  },
};

// ── Store ──────────────────────────────────────────────────────

type AgentV2Info = {
  agentId: string;
  connectorTypeV2: string;
  capabilities: FrameworkCapabilities | null;
  status: string;
};

type AgentStoreV2 = {
  agents: Record<string, AgentV2Info>;
  setAgent: (agentId: string, info: Partial<AgentV2Info>) => void;
  removeAgent: (agentId: string) => void;
  getCapabilities: (agentId: string) => FrameworkCapabilities | null;
};

export const useAgentStoreV2 = create<AgentStoreV2>((set, get) => ({
  agents: {},

  setAgent: (agentId, info) =>
    set((state) => ({
      agents: {
        ...state.agents,
        [agentId]: {
          ...state.agents[agentId],
          ...info,
          agentId,
        },
      },
    })),

  removeAgent: (agentId) =>
    set((state) => {
      const next = { ...state.agents };
      delete next[agentId];
      return { agents: next };
    }),

  getCapabilities: (agentId) => {
    const agent = get().agents[agentId];
    if (agent?.capabilities) return agent.capabilities;
    // Fallback to preset
    const connectorType = agent?.connectorTypeV2 || "";
    return FRAMEWORK_PRESETS[connectorType] || null;
  },
}));
