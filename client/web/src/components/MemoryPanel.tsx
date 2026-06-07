import { useState, useEffect } from "react";

interface Memory {
  id: string;
  type: string;
  tier: string;
  content: Record<string, unknown>;
  importance: number;
  tags: string[];
  created_at: string;
  similarity?: number;
}

const TIER_COLORS: Record<string, string> = {
  core: "text-accent-rose border-accent-rose/30 bg-accent-rose/10",
  working: "text-accent-amber border-accent-amber/30 bg-accent-amber/10",
  buffer: "text-accent-teal border-accent-teal/30 bg-accent-teal/10",
  archived: "text-surface-muted border-surface-border bg-surface-darker",
};

export function MemoryPanel({ agentId }: { agentId: string }) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [tier, setTier] = useState("working");

  const fetchMemories = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`http://localhost:50051/api/agents/${agentId}/memories?tier=${tier}&limit=50`);
      const data = await resp.json();
      setMemories(data.memories || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const searchMemories = async () => {
    if (!query.trim()) return fetchMemories();
    setLoading(true);
    try {
      const resp = await fetch(`http://localhost:50051/api/agents/${agentId}/memories/recall`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, tier, limit: 10 }),
      });
      const data = await resp.json();
      setMemories(data.results || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const promoteMemory = async (id: string, newTier: string) => {
    await fetch(`http://localhost:50051/api/memories/${id}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier: newTier }),
    });
    fetchMemories();
  };

  const archiveMemory = async (id: string) => {
    await fetch(`http://localhost:50051/api/memories/${id}/archive`, { method: "POST" });
    fetchMemories();
  };

  useEffect(() => { fetchMemories(); }, [agentId, tier]);

  return (
    <div className="space-y-3">
      {/* Search + Tier filter */}
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && searchMemories()}
          placeholder="语义搜索记忆..."
          className="flex-1 px-3 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-xs placeholder:text-surface-muted/50"
        />
        <select value={tier} onChange={(e) => setTier(e.target.value)}
          className="px-2 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-xs">
          <option value="core">Core</option>
          <option value="working">Working</option>
          <option value="buffer">Buffer</option>
        </select>
      </div>

      {/* Memory list */}
      <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
        {loading && <div className="text-surface-muted text-xs py-4 text-center">加载中...</div>}
        {!loading && memories.length === 0 && (
          <div className="text-surface-muted text-xs py-4 text-center">暂无记忆</div>
        )}
        {memories.map((m) => (
          <div key={m.id} className={`flex items-start gap-2 px-2.5 py-2 rounded-lg border ${TIER_COLORS[m.tier] || "border-white/5"}`}>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className={`text-[10px] font-medium uppercase ${TIER_COLORS[m.tier]?.split(" ")[0] || "text-surface-muted"}`}>
                  {m.tier}
                </span>
                {m.similarity && (
                  <span className="text-[10px] text-accent-teal">{Math.round(m.similarity * 100)}% match</span>
                )}
                <span className="text-[10px] text-surface-muted/50 ml-auto">{m.type}</span>
              </div>
              <div className="text-[11px] text-white/70 truncate">
                {JSON.stringify(m.content).slice(0, 100)}
              </div>
              {m.tags?.length > 0 && (
                <div className="flex gap-1 mt-1">
                  {m.tags.slice(0, 3).map((t) => (
                    <span key={t} className="px-1 py-0.5 rounded text-[9px] bg-white/5 text-surface-muted">{t}</span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex flex-col gap-1 shrink-0">
              <button onClick={() => promoteMemory(m.id, "core")} className="text-[10px] text-brand-400 hover:text-brand-300" title="升级到 Core">★</button>
              <button onClick={() => archiveMemory(m.id)} className="text-[10px] text-surface-muted hover:text-accent-rose" title="归档">↓</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
