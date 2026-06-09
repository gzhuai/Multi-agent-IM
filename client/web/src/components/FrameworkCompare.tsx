import { useState, useEffect } from "react";

interface FrameworkStats {
  calls: number;
  errors: number;
  error_rate_pct: number;
  avg_latency_ms: number;
  total_tokens_in: number;
  total_tokens_out: number;
  avg_tokens_per_call: number;
  models: string[];
}

interface CallRecord {
  connector: string;
  model: string;
  agent_id: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  success: boolean;
  timestamp: string;
}

// v2: Framework labels (brain frameworks, not LLM providers)
const FRAMEWORK_LABELS: Record<string, string> = {
  anthropic_agent: "🦾 Anthropic Agent",
  hermes_agent: "🔮 Hermes Agent",
  workflow_engine: "🔀 Workflow Engine",
  claude_code: "Claude API (旧版)",
  openai_compatible: "OpenAI Compatible (旧版)",
};

const FRAMEWORK_COLORS: Record<string, string> = {
  claude_code: "border-accent-purple",
  openai_compatible: "border-accent-teal",
};

export function FrameworkCompare() {
  const [data, setData] = useState<{ frameworks: Record<string, FrameworkStats>; recent_calls: CallRecord[] } | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const resp = await fetch("http://localhost:50051/api/metrics/frameworks");
      setData(await resp.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  if (loading) return <div className="text-surface-muted text-xs py-4 text-center">加载中...</div>;
  if (!data || Object.keys(data.frameworks).length === 0) {
    // v2: Show framework capability comparison instead of "no data"
    return <FrameworkCapabilityOverview />;
  }

  return (
    <div className="space-y-4">
      {/* Framework comparison cards */}
      <div className="grid grid-cols-2 gap-3">
        {Object.entries(data.frameworks).map(([name, stats]) => (
          <div key={name} className={`rounded-xl bg-surface-darker border-l-[3px] ${FRAMEWORK_COLORS[name] || "border-surface-border"} p-4`}>
            <div className="text-[13px] text-white font-semibold mb-2">{FRAMEWORK_LABELS[name] || name}</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <div className="text-surface-muted">调用次数</div>
              <div className="text-white text-right font-mono">{stats.calls}</div>
              <div className="text-surface-muted">平均延迟</div>
              <div className={`text-right font-mono ${stats.avg_latency_ms < 1000 ? "text-accent-green" : stats.avg_latency_ms < 3000 ? "text-accent-amber" : "text-accent-rose"}`}>
                {stats.avg_latency_ms < 1000 ? `${stats.avg_latency_ms.toFixed(0)}ms` : `${(stats.avg_latency_ms / 1000).toFixed(1)}s`}
              </div>
              <div className="text-surface-muted">错误率</div>
              <div className={`text-right font-mono ${stats.error_rate_pct === 0 ? "text-accent-green" : "text-accent-rose"}`}>
                {stats.error_rate_pct}%
              </div>
              <div className="text-surface-muted">Tokens/调用</div>
              <div className="text-white text-right font-mono">{stats.avg_tokens_per_call}</div>
            </div>
            {stats.models.length > 0 && (
              <div className="flex gap-1 mt-2 flex-wrap">
                {stats.models.map((m) => (
                  <span key={m} className="px-1.5 py-0.5 rounded text-[9px] bg-white/10 text-surface-muted">{m}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Recent calls table */}
      {data.recent_calls.length > 0 && (
        <div>
          <div className="text-[11px] text-surface-muted uppercase tracking-wider mb-2">最近调用</div>
          <div className="space-y-1 max-h-[180px] overflow-y-auto">
            {data.recent_calls.slice().reverse().map((c, i) => (
              <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-surface-darker/50 text-[11px]">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${c.success ? "bg-accent-green" : "bg-accent-rose"}`} />
                <span className="text-white/80 w-16 shrink-0 font-mono">{c.connector.slice(0, 10)}</span>
                <span className="text-surface-muted w-12 shrink-0 font-mono">{c.latency_ms}ms</span>
                <span className="text-surface-muted/50 w-24 shrink-0 truncate">{c.model}</span>
                <span className="text-surface-muted/40 ml-auto text-[10px]">{c.timestamp.slice(11, 19)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <button onClick={fetchData} className="w-full py-1.5 rounded-lg bg-white/5 text-surface-muted text-xs hover:bg-white/10 transition-colors">
        🔄 刷新
      </button>
    </div>
  );
}

/** v2: Framework capability overview shown when no API metric data is available. */
function FrameworkCapabilityOverview() {
  return (
    <div className="space-y-3">
      <div className="text-xs text-surface-muted text-center">框架能力对比（v2 — 三个大脑框架）</div>
      {[
        {
          name: "🦾 Anthropic Agent", caps: "12工具·200K上下文·Shell/Git·流式",
          color: "border-orange-400", bg: "bg-orange-500/10",
          pros: ["完整工程能力", "Anthropic Prompt Caching", "200K 上下文窗口"],
        },
        {
          name: "🔮 Hermes Agent", caps: "70+工具·28工具集·多步规划",
          color: "border-purple-400", bg: "bg-purple-500/10",
          pros: ["70+ 内置工具", "Think-Act-Observe 循环", "浏览器自动化"],
        },
        {
          name: "🔀 Workflow Engine", caps: "DAG编排·并行分发·失败策略",
          color: "border-teal-400", bg: "bg-teal-500/10",
          pros: ["多Agent DAG", "并行节点执行", "skip/continue/abort 策略"],
        },
      ].map((fw) => (
        <div key={fw.name} className={`rounded-xl border-l-[3px] ${fw.color} ${fw.bg} p-3`}>
          <div className="text-[13px] font-semibold text-white mb-1">{fw.name}</div>
          <div className="text-[11px] text-surface-muted mb-2">{fw.caps}</div>
          <div className="space-y-0.5">
            {fw.pros.map((p, i) => (
              <div key={i} className="text-[10px] text-surface-400">• {p}</div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
