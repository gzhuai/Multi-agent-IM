import { useState } from "react";
import { useAgentStore } from "../stores/agentStore";
import { useAuthStore } from "../stores/authStore";
import { SoulRadar } from "../components/SoulRadar";
import { MemoryPanel } from "../components/MemoryPanel";
import { FrameworkCompare } from "../components/FrameworkCompare";

const agentColors = [
  "from-brand-400 via-brand-500 to-accent-purple",
  "from-accent-teal via-cyan-400 to-brand-500",
  "from-accent-orange via-amber-400 to-accent-rose",
  "from-accent-green via-emerald-400 to-accent-teal",
  "from-accent-purple via-violet-400 to-accent-pink",
];

const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  OFFLINE:  { color: "text-surface-muted", bg: "bg-surface-border", label: "离线" },
  IDLE:     { color: "text-accent-green", bg: "bg-accent-green", label: "空闲" },
  THINKING: { color: "text-accent-amber", bg: "bg-accent-amber", label: "思考中" },
  WORKING:  { color: "text-brand-500", bg: "bg-brand-500", label: "工作中" },
  WAITING:  { color: "text-accent-orange", bg: "bg-accent-orange", label: "等待反馈" },
  PAUSED:   { color: "text-accent-rose", bg: "bg-accent-rose", label: "已暂停" },
};

const personalityPresets = [
  { label: "激进创新者", desc: "敢于冒险，快速决策", openness: 0.85, conscientiousness: 0.5, extraversion: 0.7, agreeableness: 0.3, directness: 0.8, risk: 0.75, color: "from-accent-orange via-amber-400 to-accent-rose" },
  { label: "稳健执行者", desc: "关注细节，可靠交付", openness: 0.3, conscientiousness: 0.9, extraversion: 0.4, agreeableness: 0.8, directness: 0.4, risk: 0.25, color: "from-accent-green via-emerald-400 to-accent-teal" },
  { label: "数据分析师", desc: "数据驱动，严谨逻辑", openness: 0.5, conscientiousness: 0.85, extraversion: 0.2, agreeableness: 0.6, directness: 0.6, risk: 0.2, color: "from-brand-400 via-brand-500 to-accent-indigo" },
  { label: "创意总监", desc: "天马行空，善于联想", openness: 0.95, conscientiousness: 0.4, extraversion: 0.8, agreeableness: 0.5, directness: 0.6, risk: 0.7, color: "from-accent-purple via-violet-400 to-accent-pink" },
];

export function AgentsPage() {
  const agents = useAgentStore((s) => s.agents);
  const token = useAuthStore((s) => s.token);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "", display_name: "", role: "", department: "",
    background: "", preset: 0,
    connector_type_v2: "anthropic_agent",  // v2: framework identifier
    connector_model: "claude-sonnet-4-6",
  });
  const [mdFiles, setMdFiles] = useState<{ name: string; content: string }[]>([]);
  const [detailAgent, setDetailAgent] = useState<string | null>(null);
  const [retrospecting, setRetrospecting] = useState(false);
  const [retrospectResult, setRetrospectResult] = useState<Record<string, unknown> | null>(null);

  const onlineCount = agents.filter(a => a.status !== "OFFLINE").length;
  const workingCount = agents.filter(a => a.status === "WORKING" || a.status === "THINKING").length;
  const idleCount = agents.filter(a => a.status === "IDLE").length;

  const createAgent = async () => {
    setCreating(true);
    const preset = personalityPresets[form.preset];
    try {
      const resp = await fetch("http://localhost:50051/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name, display_name: form.display_name || form.name,
          role: form.role, department: form.department,
          // v2: framework identifier
          connector_type_v2: form.connector_type_v2,
          connector_config: {
            model: form.connector_model,
          },
          identity: { name: form.name, display_name: form.display_name || form.name, role: form.role, department: form.department, background: form.background },
          knowledge_documents: mdFiles,
          persona: {
            openness: preset.openness, conscientiousness: preset.conscientiousness, extraversion: preset.extraversion, agreeableness: preset.agreeableness, neuroticism: 0.3,
            communication: { verbosity: 0.6, formality: 0.4, humor: 0.2, directness: preset.directness },
            decision_making: { risk_tolerance: preset.risk, data_driven: 0.7, speed_accuracy: 0.5, autonomy: 0.6 },
          },
          value_system: { core_principles: ["用户价值优先", "数据驱动决策"], red_lines: ["不能修改生产数据库", "不能代替人类做预算审批"] },
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        useAgentStore.getState().setAgents([...agents, { id: data.id, name: data.name, displayName: data.display_name || data.name, role: data.role || "", department: data.department || "", status: "OFFLINE" }]);
        setShowCreate(false);
        setForm({ name: "", display_name: "", role: "", department: "", background: "", preset: 0, connector_type_v2: "anthropic_agent", connector_model: "claude-sonnet-4-6" });
      }
    } catch (e) { console.error(e); }
    finally { setCreating(false); }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-surface-light">
      {/* Hero gradient banner */}
      <div className="bg-gradient-to-r from-brand-600 via-brand-500 to-accent-purple relative overflow-hidden">
        <div className="absolute inset-0 opacity-20">
          <div className="absolute -top-24 -right-24 w-96 h-96 bg-white rounded-full blur-3xl" />
          <div className="absolute -bottom-32 -left-32 w-80 h-80 bg-accent-pink rounded-full blur-3xl" />
        </div>
        <div className="relative max-w-4xl mx-auto px-8 py-10">
          <h2 className="text-3xl font-bold text-white mb-2">AI 员工</h2>
          <p className="text-white/70 text-sm">创建和管理你的数字员工团队，赋予每个 AI 独特的灵魂与技能</p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-8 -mt-6 relative z-10">
        {/* Stats — bold gradients */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[
            { label: "全部员工", value: agents.length, icon: "🤖", gradient: "from-slate-700 via-slate-600 to-slate-500" },
            { label: "在线", value: onlineCount, icon: "⚡", gradient: "from-brand-500 via-brand-400 to-accent-teal" },
            { label: "忙碌中", value: workingCount, icon: "🔥", gradient: "from-accent-orange via-amber-400 to-accent-rose" },
            { label: "空闲", value: idleCount, icon: "✨", gradient: "from-accent-purple via-violet-400 to-accent-pink" },
          ].map((s, i) => (
            <div key={i} className={`rounded-2xl bg-gradient-to-br ${s.gradient} p-5 text-white shadow-lg relative overflow-hidden group cursor-default`}>
              <div className="absolute top-0 right-0 w-20 h-20 bg-white/10 rounded-full -translate-y-1/2 translate-x-1/2 group-hover:scale-150 transition-transform duration-500" />
              <div className="relative">
                <div className="text-3xl mb-3">{s.icon}</div>
                <div className="text-3xl font-bold tracking-tight">{s.value}</div>
                <div className="text-sm text-white/70 mt-1 font-medium">{s.label}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Toolbar */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm text-surface-muted font-medium">{agents.length} 位员工</span>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2.5 bg-surface-dark hover:bg-surface-darker text-white rounded-xl text-sm font-semibold transition-all flex items-center gap-1.5 shadow-lg shadow-surface-dark/20"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            创建 AI 员工
          </button>
        </div>

        {/* Agent grid */}
        <div className="grid grid-cols-2 gap-4 pb-8">
          {agents.map((agent, idx) => {
            const status = statusConfig[agent.status];
            const gradient = agentColors[idx % agentColors.length];
            return (
              <div key={agent.id}
                onClick={() => setDetailAgent(detailAgent === agent.id ? null : agent.id)}
                className="group bg-surface-white border border-surface-gray rounded-2xl p-5 hover:border-brand-200 hover:shadow-card-hover transition-all duration-200 cursor-pointer">
                <div className="flex items-start gap-4">
                  <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${gradient} flex items-center justify-center text-white text-lg font-bold shadow-md shrink-0`}>
                    {agent.displayName[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-surface-dark">{agent.displayName}</h3>
                      <div className={`w-1.5 h-1.5 rounded-full ${status.bg}`} />
                      <span className={`text-xs font-medium ${status.color}`}>{status.label}</span>
                    </div>
                    <p className="text-sm text-surface-muted mt-0.5">{agent.role} · {agent.department}</p>
                    {/* Mini skill bar */}
                    <div className="mt-3 flex gap-1.5">
                      {["分析", "沟通", "决策", "创造"].map((skill, si) => (
                        <div key={si} className="flex-1 h-1 rounded-full bg-surface-gray overflow-hidden">
                          <div className={`h-full rounded-full bg-gradient-to-r ${gradient}`}
                            style={{ width: `${40 + Math.random() * 50}%` }} />
                        </div>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      const action = agent.status === "OFFLINE" ? "activate" : "pause";
                      try { await fetch(`http://localhost:50051/api/agents/${agent.id}/${action}`, { method: "POST" }); }
                      catch (e) {}
                    }}
                    className={`shrink-0 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                      agent.status === "OFFLINE"
                        ? "bg-accent-green/10 text-accent-green hover:bg-accent-green/20"
                        : "bg-surface-light text-surface-muted hover:bg-surface-gray"
                    }`}
                  >
                    {agent.status === "OFFLINE" ? "激活" : "暂停"}
                  </button>
                </div>
              </div>
            );
          })}
          {agents.length === 0 && (
            <div className="col-span-2 text-center py-20">
              <div className="w-24 h-24 mx-auto mb-6 rounded-3xl bg-gradient-to-br from-brand-100 to-purple-100 flex items-center justify-center text-5xl shadow-glow">🤖</div>
              <h3 className="text-surface-dark font-bold text-xl mb-2">还没有 AI 员工</h3>
              <p className="text-surface-muted mb-6">创建一个数字员工，赋予它灵魂和技能</p>
              <button onClick={() => setShowCreate(true)} className="px-6 py-3 bg-brand-500 hover:bg-brand-600 text-white rounded-xl text-sm font-semibold transition-colors shadow-lg shadow-brand-500/25">
                创建第一个 AI 员工
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Agent Detail Panel */}
      {detailAgent && (() => {
        const agent = agents.find(a => a.id === detailAgent);
        if (!agent) return null;
        return (
          <div className="fixed inset-0 z-40 flex items-start justify-center pt-20 bg-black/40" onClick={() => setDetailAgent(null)}>
            <div className="bg-surface-dark rounded-2xl w-[640px] max-h-[80vh] overflow-y-auto shadow-2xl border border-white/10 mx-4" onClick={e => e.stopPropagation()}>
              {/* Header */}
              <div className="sticky top-0 bg-surface-dark border-b border-white/5 px-6 py-4 flex items-center justify-between rounded-t-2xl z-10">
                <div>
                  <h2 className="text-white font-bold text-lg">{agent.displayName}</h2>
                  <p className="text-surface-muted text-sm">{agent.role} · {agent.department}</p>
                </div>
                <button onClick={() => setDetailAgent(null)} className="text-surface-muted hover:text-white text-xl">✕</button>
              </div>

              {/* v2: Brain Framework selector */}
              <div className="px-6 py-5 border-b border-white/5">
                <h3 className="text-[13px] font-semibold text-white mb-3">🧠 大脑框架</h3>
                <div className="flex items-center gap-2">
                  <select
                    onChange={async (e) => {
                      const framework = e.target.value;
                      if (!framework) return;
                      await fetch(`http://localhost:50051/api/agents/${agent.id}/connector`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ connector_type_v2: framework, connector_config: {} }),
                      });
                    }}
                    className="px-3 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-xs"
                  >
                    <option value="anthropic_agent">🦾 Anthropic Agent (12工具·工程能力)</option>
                    <option value="hermes_agent">🔮 Hermes Agent (70+工具·自主规划)</option>
                    <option value="workflow_engine">🔀 Workflow Engine (DAG编排)</option>
                  </select>
                  <span className="text-surface-muted text-xs">切换后下次推理生效</span>
                </div>
                {/* Framework capability preview */}
                <div className="mt-3 grid grid-cols-3 gap-1.5">
                  {[
                    { label: "文件读写", key: "file" },
                    { label: "Shell执行", key: "shell" },
                    { label: "代码搜索", key: "search" },
                    { label: "Git操作", key: "git" },
                    { label: "子Agent", key: "delegate" },
                    { label: "多步规划", key: "plan" },
                  ].map((cap) => (
                    <div key={cap.key} className="px-2 py-1 rounded bg-white/5 text-[10px] text-white/60 text-center">
                      {cap.label}
                    </div>
                  ))}
                </div>
              </div>

              {/* Soul Radar */}
              <div className="px-6 py-5 border-b border-white/5">
                <h3 className="text-[13px] font-semibold text-white mb-3">灵魂画像</h3>
                <SoulRadar traits={{
                  openness: 0.7,
                  conscientiousness: 0.8,
                  extraversion: 0.5,
                  agreeableness: 0.4,
                  neuroticism: 0.3,
                  directness: 0.65,
                }} size={220} />
              </div>

              {/* Memory Panel */}
              <div className="px-6 py-5 border-b border-white/5">
                <h3 className="text-[13px] font-semibold text-white mb-3">记忆</h3>
                <MemoryPanel agentId={agent.id} />
              </div>

              {/* Framework comparison */}
              <div className="px-6 py-5 border-b border-white/5">
                <h3 className="text-[13px] font-semibold text-white mb-3">🔌 LLM 框架性能</h3>
                <FrameworkCompare />
              </div>

              {/* Retrospect */}
              <div className="px-6 py-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[13px] font-semibold text-white">自我复盘</h3>
                  <button
                    onClick={async () => {
                      setRetrospecting(true);
                      setRetrospectResult(null);
                      try {
                        const resp = await fetch(`http://localhost:50051/api/agents/${agent.id}/retrospect`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ period_days: 7 }),
                        });
                        const data = await resp.json();
                        setRetrospectResult(data);
                      } catch (e) { console.error(e); }
                      setRetrospecting(false);
                    }}
                    disabled={retrospecting}
                    className="px-3 py-1.5 rounded-lg bg-brand-500/20 border border-brand-500/30 text-brand-400 text-xs hover:bg-brand-500/30 disabled:opacity-40 transition-colors"
                  >
                    {retrospecting ? "复盘分析中..." : "🤖 开始复盘"}
                  </button>
                </div>
                {retrospectResult && (
                  <div className="space-y-2 text-sm">
                    <p className="text-white/80">{retrospectResult.summary as string}</p>
                    {Array.isArray(retrospectResult.key_findings) && (retrospectResult.key_findings as string[]).length > 0 && (
                      <div>
                        <span className="text-[11px] text-surface-muted uppercase tracking-wider">关键发现</span>
                        {(retrospectResult.key_findings as string[]).map((f: string, i: number) => (
                          <div key={i} className="text-accent-amber/80 text-xs mt-1">💡 {f}</div>
                        ))}
                      </div>
                    )}
                    {retrospectResult.candidate_core_memories && Array.isArray(retrospectResult.candidate_core_memories) && (retrospectResult.candidate_core_memories as string[]).length > 0 && (
                      <div>
                        <span className="text-[11px] text-surface-muted uppercase tracking-wider">候选核心记忆</span>
                        {(retrospectResult.candidate_core_memories as string[]).map((m: string, i: number) => (
                          <div key={i} className="text-accent-teal/80 text-xs mt-1">🧠 {m}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-surface-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 bg-surface-white z-10 px-6 py-4 border-b border-surface-gray flex items-center justify-between rounded-t-2xl">
              <h3 className="text-lg font-bold text-surface-dark">创建 AI 员工</h3>
              <button onClick={() => setShowCreate(false)} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-light text-surface-muted hover:text-surface-dark transition-colors">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="p-6 space-y-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-surface-dark mb-1.5">姓名 <span className="text-accent-rose">*</span></label>
                  <input value={form.name} onChange={(e) => setForm({...form, name: e.target.value})}
                    placeholder="陈思远" className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-xl text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-surface-dark mb-1.5">显示名称</label>
                  <input value={form.display_name} onChange={(e) => setForm({...form, display_name: e.target.value})}
                    placeholder="思远·产品" className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-xl text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-surface-dark mb-1.5">职位 <span className="text-accent-rose">*</span></label>
                  <input value={form.role} onChange={(e) => setForm({...form, role: e.target.value})}
                    placeholder="高级产品经理" className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-xl text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-surface-dark mb-1.5">部门</label>
                  <input value={form.department} onChange={(e) => setForm({...form, department: e.target.value})}
                    placeholder="产品部" className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-xl text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-surface-dark mb-1.5">背景故事</label>
                <textarea value={form.background} onChange={(e) => setForm({...form, background: e.target.value})}
                  placeholder="描述这个 AI 员工的经历、特点和口头禅..." rows={3}
                  className="w-full px-3 py-2.5 bg-surface-light border border-surface-border rounded-xl text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all resize-none" />
              </div>

              {/* MD 文档上传 */}
              <div>
                <label className="block text-xs font-semibold text-surface-dark mb-1.5">
                  知识文档 (.md)
                  <span className="text-surface-muted font-normal ml-1">— 导入后注入 AI 记忆</span>
                </label>
                <label className="flex flex-col items-center gap-2 px-4 py-5 border-2 border-dashed border-surface-border rounded-xl cursor-pointer hover:border-brand-300 hover:bg-brand-50/30 transition-all group">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand-100 to-purple-100 flex items-center justify-center text-xl group-hover:scale-110 transition-transform">
                    📄
                  </div>
                  <span className="text-sm text-surface-muted group-hover:text-brand-600 transition-colors font-medium">
                    点击上传 .md 文件
                  </span>
                  <span className="text-xxs text-surface-muted">
                    支持员工手册、产品文档、流程规范等
                  </span>
                  <input
                    type="file"
                    accept=".md,.markdown,.txt"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      const files = e.target.files;
                      if (!files) return;
                      const readers: Promise<{ name: string; content: string }>[] = [];
                      for (let i = 0; i < files.length; i++) {
                        const file = files[i];
                        readers.push(new Promise((resolve) => {
                          const reader = new FileReader();
                          reader.onload = (ev) => resolve({ name: file.name, content: ev.target?.result as string || "" });
                          reader.readAsText(file);
                        }));
                      }
                      Promise.all(readers).then((results) => {
                        setMdFiles((prev) => [...prev, ...results]);
                      });
                    }}
                  />
                </label>
                {/* Uploaded files list */}
                {mdFiles.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {mdFiles.map((f, i) => (
                      <div key={i} className="flex items-center gap-2 px-3 py-1.5 bg-brand-50 rounded-lg text-xs">
                        <span className="text-brand-500">📄</span>
                        <span className="text-surface-dark truncate flex-1">{f.name}</span>
                        <span className="text-surface-muted">{f.content.length} 字</span>
                        <button
                          onClick={() => setMdFiles((prev) => prev.filter((_, j) => j !== i))}
                          className="text-surface-muted hover:text-accent-rose transition-colors ml-1"
                        >×</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* v2: Brain Framework Selector — replaces LLM Backend Selector */}
              <div>
                <label className="block text-xs font-semibold text-surface-dark mb-2">🧠 大脑框架</label>
                <div className="space-y-2 mb-3">
                  {[
                    {
                      key: "anthropic_agent", label: "Anthropic Agent", icon: "🦾",
                      desc: "完整工程能力 — 读写文件、执行Shell、Git操作、代码搜索",
                      caps: "12 工具 · 200K 上下文 · 流式输出",
                      color: "border-orange-300 bg-orange-50",
                      active: "border-orange-400 bg-orange-100 ring-2 ring-orange-200",
                    },
                    {
                      key: "hermes_agent", label: "Hermes Agent", icon: "🔮",
                      desc: "70+ 工具 · 多步规划 · 子Agent委派 · 浏览器自动化",
                      caps: "NousResearch · 自主进化 · 28 工具集",
                      color: "border-purple-300 bg-purple-50",
                      active: "border-purple-400 bg-purple-100 ring-2 ring-purple-200",
                    },
                    {
                      key: "workflow_engine", label: "Workflow Engine", icon: "🔀",
                      desc: "DAG 多Agent编排 · 并行分发 · 失败策略 · 状态追踪",
                      caps: "轻量自建 · 无外部依赖",
                      color: "border-teal-300 bg-teal-50",
                      active: "border-teal-400 bg-teal-100 ring-2 ring-teal-200",
                    },
                  ].map((fw) => {
                    const isActive = form.connector_type_v2 === fw.key;
                    return (
                      <button key={fw.key}
                        onClick={() => setForm({...form, connector_type_v2: fw.key})}
                        className={`w-full p-3 rounded-xl text-left border-2 transition-all duration-200 ${
                          isActive ? fw.active : fw.color + " hover:border-gray-300"
                        }`}>
                        <div className="flex items-center gap-2">
                          <span className="text-xl">{fw.icon}</span>
                          <div>
                            <div className="text-sm font-bold text-surface-dark">{fw.label}</div>
                            <div className="text-[11px] text-surface-muted mt-0.5">{fw.desc}</div>
                            <div className="text-[10px] text-surface-muted/70 mt-0.5 font-mono">{fw.caps}</div>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
                {/* Framework-specific model selector */}
                <div className="grid grid-cols-2 gap-2 mb-1">
                  <input value={form.connector_model} onChange={(e) => setForm({...form, connector_model: e.target.value})}
                    placeholder="模型 (如 claude-sonnet-4-6)" className="px-3 py-2 bg-surface-light border border-surface-border rounded-xl text-sm" />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-surface-dark mb-2">人格预设</label>
                <div className="grid grid-cols-2 gap-2">
                  {personalityPresets.map((p, i) => (
                    <button key={i} onClick={() => setForm({...form, preset: i})}
                      className={`p-3 rounded-xl text-left border-2 transition-all duration-200 ${
                        form.preset === i
                          ? "border-brand-400 bg-brand-50 shadow-sm"
                          : "border-surface-gray hover:border-surface-border bg-surface-white"
                      }`}>
                      <div className={`text-sm font-bold bg-gradient-to-r ${p.color} bg-clip-text text-transparent`}>{p.label}</div>
                      <div className="text-xs text-surface-muted mt-0.5">{p.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="sticky bottom-0 bg-surface-white px-6 py-4 border-t border-surface-gray flex gap-3 justify-end rounded-b-2xl">
              <button onClick={() => setShowCreate(false)}
                className="px-5 py-2.5 border border-surface-border text-surface-dark rounded-xl text-sm hover:bg-surface-light transition-colors font-medium">取消</button>
              <button onClick={createAgent} disabled={creating || !form.name || !form.role}
                className="px-6 py-2.5 bg-gradient-to-r from-brand-500 to-brand-600 hover:from-brand-600 hover:to-brand-700 disabled:opacity-40 text-white rounded-xl text-sm font-semibold transition-all shadow-lg shadow-brand-500/25">
                {creating ? "创建中..." : "创建 AI 员工"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
