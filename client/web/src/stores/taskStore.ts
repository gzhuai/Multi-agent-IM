import { create } from "zustand";

export interface Task {
  id: string;
  title: string;
  description: string;
  creator_id: string;
  creator_type: "human" | "agent";
  assignee_id: string;
  parent_task_id?: string;
  channel_id?: string;
  status: "TODO" | "IN_PROGRESS" | "REVIEW" | "DONE" | "BLOCKED" | "CANCELLED";
  priority: "LOW" | "NORMAL" | "HIGH" | "URGENT";
  deadline?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

export interface Subtask {
  title: string;
  description: string;
  suggested_assignee: string;
  priority: string;
}

interface TaskState {
  tasks: Task[];
  stats: Record<string, number>;
  selectedTask: Task | null;
  selectedSubtasks: Task[];
  // Actions
  fetchTasks: (filters?: Record<string, string>) => Promise<void>;
  fetchTask: (id: string) => Promise<void>;
  createTask: (data: Partial<Task>) => Promise<Task | null>;
  updateStatus: (id: string, status: string) => Promise<void>;
  assignTask: (id: string, assigneeId: string) => Promise<void>;
  addSubtask: (parentId: string, data: { title: string; description: string; assignee_id?: string; priority?: string }) => Promise<void>;
  decomposeTask: (agentId: string, title: string, description: string) => Promise<Subtask[]>;
  setSelectedTask: (task: Task | null) => void;
}

const API = "/api/tasks";
const RT = "http://localhost:50051";

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: [],
  stats: {},
  selectedTask: null,
  selectedSubtasks: [],

  fetchTasks: async (filters = {}) => {
    const qs = new URLSearchParams(filters).toString();
    const resp = await fetch(`${API}?${qs}`);
    const data = await resp.json();
    set({ tasks: data.tasks || [] });
  },

  fetchTask: async (id) => {
    const resp = await fetch(`${API}/${id}`);
    const data = await resp.json();
    set({ selectedTask: data.task, selectedSubtasks: data.subtasks || [] });
  },

  createTask: async (data) => {
    const resp = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) return null;
    const task = await resp.json();
    set((s) => ({ tasks: [...s.tasks, task] }));
    return task;
  },

  updateStatus: async (id, status) => {
    await fetch(`${API}/${id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    // Refresh
    get().fetchTasks();
  },

  assignTask: async (id, assigneeId) => {
    await fetch(`${API}/${id}/assign`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignee_id: assigneeId }),
    });
    get().fetchTasks();
  },

  addSubtask: async (parentId, data) => {
    await fetch(`${API}/${parentId}/subtasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  },

  decomposeTask: async (agentId, title, description) => {
    const resp = await fetch(`${RT}/api/tasks/decompose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId, title, description }),
    });
    const data = await resp.json();
    return data.subtasks || [];
  },

  setSelectedTask: (task) => set({ selectedTask: task }),
}));
