import { useState } from "react";

export function EmergencyPanel() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const act = async (action: string) => {
    setBusy(true);
    setResult(null);
    try {
      const resp = await fetch(`http://localhost:8080/api/emergency/${action}`, { method: "POST" });
      const data = await resp.json();
      setResult(JSON.stringify(data, null, 2));
    } catch (e) {
      setResult("Error: " + String(e));
    }
    setBusy(false);
  };

  return (
    <div className="rounded-2xl border-2 border-accent-rose/40 bg-gradient-to-br from-accent-rose/10 to-surface-darker p-6 space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-accent-rose/20 flex items-center justify-center text-2xl">🚨</div>
        <div>
          <h2 className="text-white font-bold text-lg">紧急控制面板</h2>
          <p className="text-accent-rose/70 text-xs">⚠️ 谨慎操作 — 影响所有 AI 员工</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => act("pause-all")}
          disabled={busy}
          className="py-3 rounded-xl bg-accent-rose/20 border border-accent-rose/50 text-accent-rose hover:bg-accent-rose/30 disabled:opacity-40 text-sm font-bold transition-colors"
        >
          ⏸️ 暂停全部 Agent
        </button>
        <button
          onClick={() => act("resume-all")}
          disabled={busy}
          className="py-3 rounded-xl bg-accent-green/20 border border-accent-green/50 text-accent-green hover:bg-accent-green/30 disabled:opacity-40 text-sm font-bold transition-colors"
        >
          ▶️ 恢复全部 Agent
        </button>
      </div>

      {result && (
        <pre className="p-3 rounded-lg bg-black/30 text-surface-muted text-xs overflow-x-auto font-mono">
          {result}
        </pre>
      )}
    </div>
  );
}
