import { Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ChatPage } from "./pages/ChatPage";
import { AgentsPage } from "./pages/AgentsPage";
import { TasksPage } from "./pages/TasksPage";
import { LoginPage } from "./pages/LoginPage";
import { useAuthStore } from "./stores/authStore";

// DEV MODE: bypass auth for UI preview
const DEV_MODE = true;

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (DEV_MODE) return <>{children}</>;
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  if (DEV_MODE) {
    // Set fake auth so UI shows a user
    const store = useAuthStore.getState();
    if (!store.isAuthenticated) {
      useAuthStore.setState({
        token: "dev-token",
        userId: "dev-user-1",
        username: "dev",
        displayName: "开发者",
        isAuthenticated: true,
      });
    }
  }

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  return (
    <Routes>
      <Route path="/login" element={
        DEV_MODE ? <Navigate to="/" replace /> :
        isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />
      } />
      <Route element={
        <ProtectedRoute><Layout /></ProtectedRoute>
      }>
        <Route path="/" element={<ChatPage />} />
        <Route path="/channel/:channelId" element={<ChatPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/tasks" element={<TasksPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
