"""事件溯源研究内核 — 投影引擎与只读物化视图 (Projection Models & Read Views).

从不可变 Event 序列纯函数式构建实时物化视图，状态表仅为投影，随时可 100% 幂等重放重建。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from alpha_operator_framework.core.events import Event, EventType


@dataclass
class CandidateView:
    """候选 Alpha 物化视图."""

    candidate_sha: str
    expression: str
    family: str
    region: str = "GBR"
    universe: str = "TOP700"
    status: str = "generated"             # generated / simulated / validated / ready / rejected
    evidence_level: str = "synthetic"
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    returns: float = 0.0
    drawdown: float = 0.0
    pc_value: Optional[float] = None
    sc_value: Optional[float] = None
    checks_passed: bool = False
    decision_verdict: Optional[str] = None
    approved_by: Optional[str] = None
    history_events: List[str] = field(default_factory=list)


@dataclass
class FamilyStatsView:
    """因子族统计与停止状态物化视图."""

    family: str
    total_trials: int = 0
    successful_trials: int = 0
    is_stopped: bool = False
    stop_reason: Optional[str] = None


@dataclass
class OutboxItemView:
    """平台模拟 Outbox 任务项."""

    request_event_id: str
    candidate_sha: str
    idempotency_key: str
    expression: str
    settings: Dict[str, Any]
    status: str = "pending"  # pending / accepted / completed / failed
    platform_sim_id: Optional[str] = None


class ProjectionEngine:
    """物化视图投影引擎."""

    def __init__(self):
        self.candidates: Dict[str, CandidateView] = {}
        self.family_stats: Dict[str, FamilyStatsView] = {}
        self.outbox_items: Dict[str, OutboxItemView] = {}
        self.approved_registry: List[CandidateView] = []

    def apply(self, event: Event) -> None:
        """纯函数式应用单个事件并更新内部视图."""
        etype = event.event_type
        payload = event.payload

        if etype == EventType.CANDIDATE_GENERATED:
            csha = payload.get("candidate_sha", "")
            fam = payload.get("family", "default")
            expr = payload.get("expression", "")
            if csha:
                cand = CandidateView(
                    candidate_sha=csha,
                    expression=expr,
                    family=fam,
                    region=payload.get("region", "GBR"),
                    universe=payload.get("universe", "TOP700"),
                    status="generated",
                    history_events=[event.event_id],
                )
                self.candidates[csha] = cand

                # 累加因子族试验数
                if fam not in self.family_stats:
                    self.family_stats[fam] = FamilyStatsView(family=fam)
                self.family_stats[fam].total_trials += 1

        elif etype == EventType.SIMULATION_REQUESTED:
            csha = payload.get("candidate_sha", "")
            ikey = payload.get("idempotency_key", "")
            if ikey:
                self.outbox_items[ikey] = OutboxItemView(
                    request_event_id=event.event_id,
                    candidate_sha=csha,
                    idempotency_key=ikey,
                    expression=payload.get("expression", ""),
                    settings=payload.get("settings", {}),
                    status="pending",
                )

        elif etype == EventType.SIMULATION_ACCEPTED:
            ikey = payload.get("idempotency_key", "")
            if ikey in self.outbox_items:
                self.outbox_items[ikey].status = "accepted"
                self.outbox_items[ikey].platform_sim_id = payload.get("platform_sim_id")

        elif etype == EventType.SIMULATION_COMPLETED:
            csha = payload.get("candidate_sha", "")
            ikey = payload.get("idempotency_key", "")
            if ikey in self.outbox_items:
                self.outbox_items[ikey].status = "completed"

            if csha in self.candidates:
                cand = self.candidates[csha]
                cand.status = "simulated"
                cand.evidence_level = payload.get("evidence_level", "platform_is")
                cand.sharpe = float(payload.get("sharpe", 0.0))
                cand.fitness = float(payload.get("fitness", 0.0))
                cand.turnover = float(payload.get("turnover", 0.0))
                cand.returns = float(payload.get("returns", 0.0))
                cand.drawdown = float(payload.get("drawdown", 0.0))
                cand.history_events.append(event.event_id)

                if cand.sharpe >= 1.25 and cand.fitness >= 1.0:
                    if cand.family in self.family_stats:
                        self.family_stats[cand.family].successful_trials += 1

        elif etype == EventType.VALIDATION_COMPUTED:
            csha = payload.get("candidate_sha", "")
            if csha in self.candidates:
                cand = self.candidates[csha]
                cand.checks_passed = bool(payload.get("checks_passed", False))
                cand.status = "validated" if cand.checks_passed else "rejected"
                cand.history_events.append(event.event_id)

        elif etype == EventType.DECISION_APPROVED:
            csha = payload.get("candidate_sha", "")
            if csha in self.candidates:
                cand = self.candidates[csha]
                cand.status = "ready"
                cand.decision_verdict = "APPROVED"
                cand.approved_by = event.actor
                cand.history_events.append(event.event_id)
                if cand not in self.approved_registry:
                    self.approved_registry.append(cand)

        elif etype == EventType.DECISION_REJECTED:
            csha = payload.get("candidate_sha", "")
            if csha in self.candidates:
                cand = self.candidates[csha]
                cand.status = "rejected"
                cand.decision_verdict = "REJECTED"
                cand.history_events.append(event.event_id)

    def replay(self, events: Sequence[Event]) -> None:
        """从事件序列全量重放，幂等重建所有物化视图."""
        self.candidates.clear()
        self.family_stats.clear()
        self.outbox_items.clear()
        self.approved_registry.clear()
        for evt in events:
            self.apply(evt)
