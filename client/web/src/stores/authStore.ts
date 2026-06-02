import { create } from "zustand";

interface AuthState {
  token: string | null;
  userId: string | null;
  username: string | null;
  displayName: string | null;
  isAuthenticated: boolean;

  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
  setAuth: (token: string, userId: string, displayName: string) => void;
}

const API = "http://localhost:3000/api/auth";

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem("token"),
  userId: localStorage.getItem("userId"),
  username: localStorage.getItem("username"),
  displayName: localStorage.getItem("displayName"),
  isAuthenticated: !!localStorage.getItem("token"),

  login: async (username, password) => {
    const resp = await fetch(`${API}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || "Login failed");
    }
    const data = await resp.json();
    localStorage.setItem("token", data.token);
    localStorage.setItem("userId", data.user_id);
    localStorage.setItem("displayName", data.display_name);
    set({
      token: data.token,
      userId: data.user_id,
      username,
      displayName: data.display_name,
      isAuthenticated: true,
    });
  },

  register: async (username, password, displayName) => {
    const resp = await fetch(`${API}/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, display_name: displayName }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || "Registration failed");
    }
    const data = await resp.json();
    localStorage.setItem("token", data.token);
    localStorage.setItem("userId", data.user_id);
    localStorage.setItem("displayName", data.display_name);
    set({
      token: data.token,
      userId: data.user_id,
      username,
      displayName: data.display_name,
      isAuthenticated: true,
    });
  },

  logout: () => {
    localStorage.removeItem("token");
    localStorage.removeItem("userId");
    localStorage.removeItem("displayName");
    set({ token: null, userId: null, username: null, displayName: null, isAuthenticated: false });
  },

  setAuth: (token, userId, displayName) => {
    set({ token, userId, displayName, isAuthenticated: true });
  },
}));
