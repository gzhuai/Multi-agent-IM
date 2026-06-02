import { useState } from "react";
import { useAuthStore } from "../stores/authStore";

export function LoginPage() {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (isRegister) {
        await register(username, password, displayName || username);
      } else {
        await login(username, password);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-surface-light">
      {/* Left — brand area */}
      <div className="hidden lg:flex flex-1 bg-gradient-to-br from-brand-600 via-brand-500 to-accent-purple items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-1/4 left-1/4 w-64 h-64 bg-white rounded-full blur-3xl" />
          <div className="absolute bottom-1/3 right-1/3 w-96 h-96 bg-accent-pink rounded-full blur-3xl" />
        </div>
        <div className="relative text-white text-center px-8">
          <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-white/20 backdrop-blur flex items-center justify-center text-3xl">
            🤖
          </div>
          <h1 className="text-3xl font-bold mb-3">Multi-agent-IM</h1>
          <p className="text-white/70 text-lg leading-relaxed">
            创建你的 AI 数字员工<br />
            让协作超越人类的边界
          </p>
        </div>
      </div>

      {/* Right — form */}
      <div className="flex-1 flex items-center justify-center px-8">
        <div className="w-full max-w-sm">
          <h2 className="text-2xl font-bold text-surface-dark mb-1">
            {isRegister ? "创建账号" : "欢迎回来"}
          </h2>
          <p className="text-surface-muted text-sm mb-8">
            {isRegister ? "注册一个新的工作空间" : "登录你的工作空间"}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <div>
                <label className="block text-xs font-medium text-surface-dark mb-1">显示名称</label>
                <input
                  type="text" placeholder="别人看到的名字"
                  value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-lg text-sm text-surface-dark outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all"
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-surface-dark mb-1">用户名</label>
              <input
                type="text" placeholder="输入用户名"
                value={username} onChange={(e) => setUsername(e.target.value)} required
                className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-lg text-sm text-surface-dark outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-surface-dark mb-1">密码</label>
              <input
                type="password" placeholder="至少 6 位"
                value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6}
                className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-lg text-sm text-surface-dark outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all"
              />
            </div>

            {error && (
              <div className="text-accent-pink text-xs bg-accent-pink/5 px-3 py-2 rounded-lg">{error}</div>
            )}

            <button
              type="submit" disabled={loading}
              className="w-full py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors"
            >
              {loading ? "请稍候..." : isRegister ? "注册" : "登录"}
            </button>
          </form>

          <p className="text-center mt-6 text-sm text-surface-muted">
            {isRegister ? "已有账号？" : "还没有账号？"}
            <button onClick={() => { setIsRegister(!isRegister); setError(""); }}
              className="text-brand-500 hover:text-brand-600 font-medium ml-1">
              {isRegister ? "去登录" : "注册一个"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
