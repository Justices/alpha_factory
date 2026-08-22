"""Candidate Exploration Bounded Context - Domain Models & Aggregate Root."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Budget:
    """Resource bounds for a single research cycle round."""
    max_generated: int = 1000
    max_pre_pruned: int = 500
    max_backtested: int = 50
    max_optimized: int = 10
    max_submitted: int = 5


@dataclass(frozen=True)
class ResearchPolicy:
    """Immutable, versioned policy specifying research constraints and algorithm selection."""
    version: str = "1.0.0"
    region: str = "GBR"
    universe: str = "TOP700"
    delay: int = 1
    decay: int = 12
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    budget: Budget = field(default_factory=Budget)
    selection_algorithm: str = "stratified"  # stratified | d_optimal | thompson | ucb | nsga2
    selection_params: Dict[str, Any] = field(default_factory=dict)
    family_quotas: Dict[str, int] = field(default_factory=dict)
    min_distinct_fields: int = 2
    pre_prune_rules: List[str] = field(default_factory=list)


@dataclass
class Candidate:
    """An exploration candidate factor expression."""
    candidate_id: str
    expression: str
    family: str
    fields: List[str]
    decay: int = 12
    canonical_hash: str = ""
    lineage_parent_id: Optional[str] = None
    generation_strategy: str = "carpet"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def compute_canonical_hash(self) -> str:
        # Standardize whitespaces
        norm = "".join(self.expression.split())
        self.canonical_hash = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        return self.canonical_hash


@dataclass(frozen=True)
class PrePruneDecision:
    """Record of a pre-backtest rejection or pass."""
    candidate_id: str
    is_rejected: bool
    reason_code: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    policy_version: str = "1.0.0"


@dataclass(frozen=True)
class SelectionDecision:
    """Decision details for candidate inclusion into the backtest cohort."""
    candidate_id: str
    is_selected: bool
    score_components: Dict[str, float]
    algorithm: str
    policy_version: str
    seed: int
    reason: str


@dataclass
class SelectionRound:
    """Aggregate Root: Owns the planned exploration round and decision lineage."""
    round_id: str
    policy: ResearchPolicy
    seed: int
    status: str = "INITIALIZED"  # INITIALIZED | GENERATED | PRE_PRUNED | SELECTED | COMPLETED
    candidate_pool: Dict[str, Candidate] = field(default_factory=dict)
    pre_prune_decisions: Dict[str, PrePruneDecision] = field(default_factory=dict)
    selection_decisions: Dict[str, SelectionDecision] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_candidate(self, candidate: Candidate) -> None:
        if not candidate.canonical_hash:
            candidate.compute_canonical_hash()
        self.candidate_pool[candidate.candidate_id] = candidate

    def record_pre_prune(self, decision: PrePruneDecision) -> None:
        self.pre_prune_decisions[decision.candidate_id] = decision

    def record_selection(self, decision: SelectionDecision) -> None:
        self.selection_decisions[decision.candidate_id] = decision

    def get_accepted_pre_pruned(self) -> List[Candidate]:
        return [
            c for c in self.candidate_pool.values()
            if c.candidate_id in self.pre_prune_decisions
            and not self.pre_prune_decisions[c.candidate_id].is_rejected
        ]

    def get_selected_cohort(self) -> List[Candidate]:
        selected_ids = {
            d.candidate_id for d in self.selection_decisions.values()
            if d.is_selected
        }
        return [c for c in self.candidate_pool.values() if c.candidate_id in selected_ids]
