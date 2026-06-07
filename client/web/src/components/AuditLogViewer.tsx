import { useState, useEffect } from "react";

interface LogEntry {
  id: string;
  agent_id: string;
  action: string;
  detail: string;
  created_at: string;
}

interface Stats {
  total: number;
  today: number;
  by_action: Record<string, number>;
}

const ACTION_LABELS: Record<string, string> = {
  agent_dispatched: "Agent 派遣",
  emergency_pause_all: "紧急暂停",
  emergency_resume_all: "紧急恢复",
  task_created: "创建任务",
  task_status_change: "任务状态变更",
};

export function AuditLogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [filter, setFilter] = useState({ action: "", since: "" });
  const [loading, setLoading] = useState(false);

  const fetchLogs = async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filter.action) params.set("action", filter.action);
    if (filter.since) params.set("since", filter.since);
    try {
      const resp = await fetch(`http://localhost:8080/api/audit-logs?${params}`);
      const data = await resp.json();
      setLogs(data.logs || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const fetchStats = async () => {
    try {
      const resp = await fetch("http://localhost:8080/api/audit-logs/stats");
      setStats(await resp.json());
    } catch (e) {}
  };

  useEffect(() => { fetchLogs(); fetchStats(); }, []);

  return (
    <div className="space-y-4">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl bg-surface-darker p-3 text-center">
            <div className="text-2xl font-bold text-white">{stats.total}</div>
            <div className="text-xs text-surface-muted">总记录</div>
          </div>
          <div className="rounded-xl bg-surface-darker p-3 text-center">
            <div className="text-2xl font-bold text-accent-teal">{stats.today}</div>
            <div className="text-xs text-surface-muted">今日</div>
          </div>
          <div className="rounded-xl bg-surface-darker p-3 text-center">
            <div className="text-2xl font-bold text-brand-400">{Object.keys(stats.by_action).length}</div>
            <div className="text-xs text-surface-muted">操作类型</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2">
        <select
          value={filter.action}
          onChange={(e) => setFilter({ ...filter, action: e.target.value })}
          className="px-3 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-xs"
        >
          <option value="">全部操作</option>
          {Object.entries(ACTION_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <input
          type="date"
          value={filter.since}
          onChange={(e) => setFilter({ ...filter, since: e.target.value })}
          className="px-3 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-xs"
        />
        <button onClick={fetchLogs} className="px-4 py-1.5 rounded-lg bg-brand-500/20 text-brand-400 text-xs hover:bg-brand-500/30">
          筛选
        </button>
      </div>

      {/* Log table */}
      <div className="max-h-[400px] overflow-y-auto space-y-1">
        {loading && <div className="text-surface-muted text-xs py-4 text-center">加载中...</div>}
        {!loading && logs.length === 0 && <div className="text-surface-muted text-xs py-4 text-center">暂无记录</div>}
        {logs.map((log) => (
          <div key={log.id} className="flex items-start gap-3 px-3 py-2 rounded-lg bg-surface-darker/50 text-xs">
            <span className="text-surface-muted/50 font-mono shrink-0 w-16">{log.created_at.slice(11, 19)}</span>
            <span className="text-brand-400 font-medium shrink-0 w-28">{ACTION_LABELS[log.action] || log.action}</span>
            <span className="text-surface-muted truncate flex-1">{log.detail?.slice(0, 120)}</span>
            <span className="text-surface-muted/40 font-mono shrink-0">{log.agent_id.slice(0, 8)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
