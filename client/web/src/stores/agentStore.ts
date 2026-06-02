import { create } from "zustand";

export interface AgentInfo {
  id: string;
  name: string;
  displayName: string;
  role: string;
  department: string;
  status: "OFFLINE" | "IDLE" | "THINKING" | "WORKING" | "WAITING" | "PAUSED";
  currentActivity: string;    // "正在撰写PRD文档"
  taskCount: number;
  priorityTasks: number;      // 高优先级任务数
  avatarUrl?: string;
}

interface AgentState {
  agents: AgentInfo[];
  selectedAgentId: string | null;
  setAgents: (agents: AgentInfo[]) => void;
  selectAgent: (id: string | null) => void;
  updateAgentStatus: (id: string, status: AgentInfo["status"]) => void;
  updateAgentActivity: (id: string, activity: string, taskCount?: number) => void;
}

// Busyness score for sorting: WORKING=4, THINKING=3, WAITING=2, IDLE=1, PAUSED=0, OFFLINE=-1
const busynessScore: Record<string, number> = {
  WORKING: 4, THINKING: 3, WAITING: 2, IDLE: 1, PAUSED: 0, OFFLINE: -1,
};

export const useAgentStore = create<AgentState>((set) => ({
  agents: [],
  selectedAgentId: null,

  setAgents: (agents) => set({ agents }),

  selectAgent: (id) => set({ selectedAgentId: id }),

  updateAgentStatus: (id, status) =>
    set((state) => ({
      agents: state.agents.map((a) => (a.id === id ? { ...a, status } : a)),
    })),

  updateAgentActivity: (id, activity, taskCount) =>
    set((state) => ({
      agents: state.agents.map((a) =>
        a.id === id
          ? { ...a, currentActivity: activity, ...(taskCount !== undefined ? { taskCount } : {}) }
          : a
      ),
    })),
}));

// Sort agents: first by busyness score, then by task count, then by priority tasks
export function sortAgentsByBusyness(agents: AgentInfo[]): AgentInfo[] {
  return [...agents].sort((a, b) => {
    const scoreA = busynessScore[a.status] + a.taskCount * 0.1 + a.priorityTasks * 0.2;
    const scoreB = busynessScore[b.status] + b.taskCount * 0.1 + b.priorityTasks * 0.2;
    return scoreB - scoreA;
  });
}
