import { useEffect, useState } from "react";
import { useTaskStore, Task } from "../stores/taskStore";
import { useAgentStore } from "../stores/agentStore";

const STATUSES = ["TODO", "IN_PROGRESS", "REVIEW", "DONE"] as const;
const STATUS_LABELS: Record<string, string> = {
  TODO: "待办",
  IN_PROGRESS: "进行中",
  REVIEW: "待审核",
  DONE: "已完成",
  BLOCKED: "已阻塞",
  CANCELLED: "已取消",
};
const STATUS_COLORS: Record<string, string> = {
  TODO: "border-surface-border",
  IN_PROGRESS: "border-accent-amber",
  REVIEW: "border-accent-purple",
  DONE: "border-accent-green",
  BLOCKED: "border-accent-rose",
};
const PRIORITY_COLORS: Record<string, string> = {
  URGENT: "bg-accent-rose text-white",
  HIGH: "bg-accent-orange/80 text-white",
  NORMAL: "bg-surface-darker text-surface-muted",
  LOW: "bg-surface-darker text-surface-muted/50",
};

export function TasksPage() {
  const { tasks, fetchTasks, updateStatus, setSelectedTask, selectedTask, selectedSubtasks, fetchTask, decomposeTask, addSubtask } = useTaskStore();
  const agents = useAgentStore((s) => s.agents);
  const [showDetail, setShowDetail] = useState(false);
  const [decomposing, setDecomposing] = useState(false);
  const [newSubtask, setNewSubtask] = useState({ title: "", description: "", assignee_id: "", priority: "NORMAL" });

  useEffect(() => { fetchTasks(); }, []);

  const tasksByStatus = (status: string) => tasks.filter((t) => t.status === status);

  const agentName = (id: string) => {
    const a = agents.find((a) => a.id === id);
    return a?.displayName || a?.name || id?.slice(0, 8) || "—";
  };

  const handleCardClick = (task: Task) => {
    setSelectedTask(task);
    fetchTask(task.id);
    setShowDetail(true);
  };

  const handleDecompose = async () => {
    if (!selectedTask) return;
    setDecomposing(true);
    const subtasks = await decomposeTask(
      selectedTask.assignee_id || agents[0]?.id || "",
      selectedTask.title,
      selectedTask.description
    );
    // Create each subtask
    for (const st of subtasks) {
      await addSubtask(selectedTask.id, {
        title: st.title,
        description: st.description,
        assignee_id: selectedTask.assignee_id,
        priority: st.priority,
      });
    }
    await fetchTask(selectedTask.id);
    setDecomposing(false);
  };

  return (
    <div className="flex-1 flex flex-col bg-surface-900 h-screen overflow-hidden">
      {/* Header */}
      <div className="h-14 flex items-center px-5 gap-4 border-b border-white/5 shrink-0">
        <h1 className="text-white font-semibold text-[15px]">📋 任务看板</h1>
        <span className="text-surface-muted text-xs">{tasks.length} 个任务</span>
        <div className="flex-1" />
        <select
          onChange={(e) => fetchTasks(e.target.value ? { assignee_id: e.target.value } : {})}
          className="px-3 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-xs"
        >
          <option value="">全部 Agent</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.displayName || a.name}</option>
          ))}
        </select>
      </div>

      {/* Kanban Board */}
      <div className="flex-1 flex gap-3 p-4 overflow-x-auto">
        {STATUSES.map((status) => (
          <div key={status} className="flex-1 min-w-[240px] flex flex-col">
            {/* Column header */}
            <div className={`flex items-center gap-2 mb-3 px-2 py-1.5 rounded-lg border-l-[3px] ${STATUS_COLORS[status]}`}>
              <span className="text-white text-[13px] font-medium">{STATUS_LABELS[status]}</span>
              <span className="text-surface-muted text-xs">{tasksByStatus(status).length}</span>
            </div>

            {/* Cards */}
            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {tasksByStatus(status).map((task) => (
                <button
                  key={task.id}
                  onClick={() => handleCardClick(task)}
                  className="w-full text-left p-3 rounded-xl bg-surface-dark border border-white/5 hover:border-white/10 transition-all group"
                >
                  <div className="flex items-start gap-2 mb-1.5">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${PRIORITY_COLORS[task.priority]}`}>
                      {task.priority === "URGENT" ? "紧急" : task.priority === "HIGH" ? "高" : task.priority === "LOW" ? "低" : "普通"}
                    </span>
                  </div>
                  <div className="text-[13px] text-white font-medium mb-1.5 leading-snug">{task.title}</div>
                  {task.description && (
                    <div className="text-[11px] text-surface-muted/70 mb-2 line-clamp-2">{task.description}</div>
                  )}
                  <div className="flex items-center gap-1.5">
                    <div className="w-4 h-4 rounded bg-gradient-to-br from-brand-400 to-accent-purple flex items-center justify-center text-[7px] text-white font-bold">
                      {agentName(task.assignee_id)[0]}
                    </div>
                    <span className="text-[10px] text-surface-muted/50">{agentName(task.assignee_id)}</span>
                    {task.deadline && (
                      <span className="ml-auto text-[10px] text-accent-amber/70">{new Date(task.deadline).toLocaleDateString("zh")}</span>
                    )}
                  </div>
                </button>
              ))}
              {tasksByStatus(status).length === 0 && (
                <div className="text-center py-8 text-surface-muted/40 text-xs">暂无任务</div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Task Detail Modal */}
      {showDetail && selectedTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowDetail(false)}>
          <div
            className="bg-surface-dark rounded-xl w-[520px] max-h-[80vh] overflow-y-auto shadow-2xl border border-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between sticky top-0 bg-surface-dark rounded-t-xl">
              <div>
                <h2 className="text-white font-semibold text-[15px]">{selectedTask.title}</h2>
                <span className={`text-[11px] ${selectedTask.status === "DONE" ? "text-accent-green" : "text-surface-muted"}`}>
                  {STATUS_LABELS[selectedTask.status]} · {agentName(selectedTask.assignee_id)}
                </span>
              </div>
              <button onClick={() => setShowDetail(false)} className="text-surface-muted hover:text-white text-lg">✕</button>
            </div>

            {/* Body */}
            <div className="px-5 py-4 space-y-4">
              {selectedTask.description && (
                <div>
                  <span className="text-[11px] text-surface-muted uppercase tracking-wider">描述</span>
                  <p className="text-[13px] text-white/80 mt-1">{selectedTask.description}</p>
                </div>
              )}

              {/* Status buttons */}
              <div>
                <span className="text-[11px] text-surface-muted uppercase tracking-wider">状态</span>
                <div className="flex gap-2 mt-1.5 flex-wrap">
                  {STATUSES.map((s) => (
                    <button
                      key={s}
                      onClick={() => { updateStatus(selectedTask.id, s); setSelectedTask({ ...selectedTask, status: s }); }}
                      className={`px-3 py-1 rounded-lg text-[12px] transition-colors ${
                        selectedTask.status === s
                          ? "bg-brand-500/20 border border-brand-500/30 text-brand-400"
                          : "bg-surface-darker border border-transparent text-surface-muted hover:bg-white/5"
                      }`}
                    >
                      {STATUS_LABELS[s]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Subtasks */}
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-surface-muted uppercase tracking-wider">子任务 ({selectedSubtasks.length})</span>
                  <button
                    onClick={handleDecompose}
                    disabled={decomposing}
                    className="text-[11px] text-brand-400 hover:text-brand-300 disabled:opacity-40"
                  >
                    {decomposing ? "拆解中..." : "🤖 AI 拆解"}
                  </button>
                </div>
                {selectedSubtasks.length > 0 && (
                  <div className="mt-1.5 space-y-1">
                    {selectedSubtasks.map((st) => (
                      <div key={st.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-surface-darker text-[12px]">
                        <span className={`w-1.5 h-1.5 rounded-full ${STATUS_COLORS[st.status]?.replace("border-", "bg-") || "bg-surface-border"}`} />
                        <span className="text-white/80 flex-1">{st.title}</span>
                        <span className="text-surface-muted/50 text-[10px]">{STATUS_LABELS[st.status]}</span>
                      </div>
                    ))}
                  </div>
                )}
                {/* Quick add subtask */}
                <div className="flex gap-2 mt-2">
                  <input
                    type="text"
                    value={newSubtask.title}
                    onChange={(e) => setNewSubtask({ ...newSubtask, title: e.target.value })}
                    placeholder="快速添加子任务..."
                    className="flex-1 px-2.5 py-1.5 rounded-lg bg-surface-darker border border-white/10 text-white text-[12px] placeholder:text-surface-muted/50"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && newSubtask.title.trim()) {
                        addSubtask(selectedTask.id, newSubtask);
                        setNewSubtask({ title: "", description: "", assignee_id: "", priority: "NORMAL" });
                      }
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
