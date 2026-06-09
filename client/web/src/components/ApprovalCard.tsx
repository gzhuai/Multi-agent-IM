/**
 * ApprovalCard — 审批卡片组件。
 *
 * 当 Agent 执行高风险操作时，在频道中显示审批卡片，
 * 人类可以点击 [批准] 或 [拒绝]。
 *
 * 超时 5 分钟后自动拒绝。
 */

import { useState, useEffect } from "react";

type ApprovalData = {
  approval_id: string;
  agent_id: string;
  agent_name: string;
  tool_name: string;
  action_description: string;
  risk_level: "safe" | "low" | "medium" | "high" | "critical";
  tool_params?: Record<string, unknown>;
  timeout_seconds?: number;
  channel_id?: string;
};

const riskColors: Record<string, string> = {
  safe: "bg-accent-green/10 border-accent-green/30 text-accent-green",
  low: "bg-accent-teal/10 border-accent-teal/30 text-accent-teal",
  medium: "bg-amber-500/10 border-amber-500/30 text-amber-400",
  high: "bg-accent-orange/10 border-accent-orange/30 text-accent-orange",
  critical: "bg-accent-rose/10 border-accent-rose/30 text-accent-rose",
};

const riskLabels: Record<string, string> = {
  safe: "安全",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  critical: "严重风险",
};

export function ApprovalCard({
  approval,
  onApprove,
  onDeny,
}: {
  approval: ApprovalData;
  onApprove?: (id: string) => void;
  onDeny?: (id: string) => void;
}) {
  const [countdown, setCountdown] = useState(approval.timeout_seconds || 300);
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    if (resolved || countdown <= 0) return;
    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(timer);
          onDeny?.(approval.approval_id);
          return 0;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [resolved, countdown, approval.approval_id, onDeny]);

  const riskColor = riskColors[approval.risk_level] || riskColors.medium;
  const riskLabel = riskLabels[approval.risk_level] || "未知";
  const minutes = Math.floor(countdown / 60);
  const seconds = countdown % 60;

  const handleApprove = () => {
    setResolved(true);
    onApprove?.(approval.approval_id);
  };

  const handleDeny = () => {
    setResolved(true);
    onDeny?.(approval.approval_id);
  };

  if (countdown <= 0 && !resolved) {
    return (
      <div className="p-3 rounded-xl border border-surface-gray bg-surface-light">
        <div className="text-sm text-surface-muted">⏰ 审批已超时（自动拒绝）</div>
      </div>
    );
  }

  if (resolved) return null;

  return (
    <div className={`p-4 rounded-xl border-2 ${riskColor} animate-pulse-slow`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">🛡️</span>
          <span className="font-bold text-sm">{approval.agent_name} 请求执行操作</span>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${riskColor}`}>
          {riskLabel}
        </span>
      </div>

      {/* Action description */}
      <div className="mb-3 text-sm">
        <span className="font-medium">{approval.action_description}</span>
        {approval.tool_params && Object.keys(approval.tool_params).length > 0 && (
          <div className="mt-1 text-xs text-surface-muted font-mono bg-surface-dark rounded-lg p-2 max-h-20 overflow-y-auto">
            {JSON.stringify(approval.tool_params, null, 2).slice(0, 300)}
          </div>
        )}
      </div>

      {/* Countdown */}
      <div className="text-xs text-surface-muted mb-3">
        ⏱ 剩余 {minutes}:{seconds.toString().padStart(2, "0")}（超时自动拒绝）
      </div>

      {/* Buttons */}
      <div className="flex gap-2">
        <button
          onClick={handleApprove}
          className="flex-1 px-4 py-2 bg-accent-green text-white rounded-xl text-sm font-semibold hover:bg-accent-green/80 transition-colors"
        >
          ✅ 批准
        </button>
        <button
          onClick={handleDeny}
          className="flex-1 px-4 py-2 bg-accent-rose/80 text-white rounded-xl text-sm font-semibold hover:bg-accent-rose transition-colors"
        >
          ❌ 拒绝
        </button>
      </div>
    </div>
  );
}
