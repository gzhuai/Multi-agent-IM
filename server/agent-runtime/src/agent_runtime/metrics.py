"""
Lightweight in-memory metrics tracker for LLM connector performance.
Tracks latency, token usage, and call counts per connector/model.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CallRecord:
    connector: str
    model: str
    agent_id: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    success: bool
    timestamp: str


class MetricsTracker:
    """Tracks LLM call metrics per connector/model."""

    def __init__(self, max_records: int = 500):
        self.records: list[CallRecord] = []
        self.max_records = max_records

    def record(
        self,
        connector: str,
        model: str,
        agent_id: str,
        latency_ms: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        success: bool = True,
    ):
        self.records.append(CallRecord(
            connector=connector,
            model=model,
            agent_id=agent_id,
            latency_ms=round(latency_ms, 1),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            success=success,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

    def compare_frameworks(self) -> dict:
        """Aggregated stats per connector."""
        groups: dict[str, dict] = defaultdict(lambda: {
            "calls": 0, "errors": 0,
            "total_latency_ms": 0.0,
            "total_tokens_in": 0, "total_tokens_out": 0,
            "models": set(),
        })
        for r in self.records:
            g = groups[r.connector]
            g["calls"] += 1
            if not r.success:
                g["errors"] += 1
            g["total_latency_ms"] += r.latency_ms
            g["total_tokens_in"] += r.tokens_in
            g["total_tokens_out"] += r.tokens_out
            g["models"].add(r.model)

        result = {}
        for name, g in groups.items():
            calls = g["calls"]
            result[name] = {
                "calls": calls,
                "errors": g["errors"],
                "error_rate_pct": round(g["errors"] / calls * 100, 1) if calls else 0,
                "avg_latency_ms": round(g["total_latency_ms"] / calls, 1) if calls else 0,
                "total_tokens_in": g["total_tokens_in"],
                "total_tokens_out": g["total_tokens_out"],
                "avg_tokens_per_call": round((g["total_tokens_in"] + g["total_tokens_out"]) / calls, 1) if calls else 0,
                "models": sorted(g["models"]),
            }
        return result

    def recent_calls(self, limit: int = 20) -> list[dict]:
        return [
            {
                "connector": r.connector,
                "model": r.model,
                "agent_id": r.agent_id[:12],
                "latency_ms": r.latency_ms,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "success": r.success,
                "timestamp": r.timestamp,
            }
            for r in self.records[-limit:]
        ]


# Global singleton
_metrics = MetricsTracker()


def get_metrics() -> MetricsTracker:
    return _metrics
