"""Candidate Exploration Bounded Context - Domain Models & Aggregate Root."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
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
class SamplingWeights:
    """Configurable weights applied by candidate selection policies."""
    field: float = 1.0
    operator: float = 1.0
    template: float = 1.0
    novelty: float = 1.0
    uncertainty: float = 1.0


@dataclass(frozen=True)
class PruningRules:
    """Immutable pre-backtest rule configuration captured with a round."""
    prohibited_patterns: tuple[str, ...] = ()
    max_expression_length: int = 4_000


@dataclass(frozen=True)
class SelectionKnowledgeSnapshot:
    """Immutable evidence consumed by a single selection round."""
    version: int = 0
    field_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    operator_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    template_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    prune_rules: tuple[str, ...] = ()

    @staticmethod
    def _score(stats: Dict[str, Dict[str, float]], keys: Sequence[str]) -> float:
        values = [float(stats.get(key, {}).get("score", 0.0)) for key in keys]
        return sum(values) / len(values) if values else 0.0

    def field_score(self, fields: Sequence[str]) -> float:
        return self._score(self.field_stats, fields)

    def operator_score(self, operators: Sequence[str]) -> float:
        return self._score(self.operator_stats, operators)

    def template_score(self, template_id: str) -> float:
        return float(self.template_stats.get(template_id, {}).get("score", 0.0))

    def uncertainty(self, candidate: "Candidate") -> float:
        trials = sum(
            float(self.field_stats.get(field, {}).get("trials", 0.0))
            for field in candidate.fields
        )
        return 1.0 / (1.0 + trials)

    def rejects(self, candidate: "Candidate") -> bool:
        return candidate.template_id in self.prune_rules


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
    weights: SamplingWeights = field(default_factory=SamplingWeights)
    pruning: PruningRules = field(default_factory=PruningRules)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ResearchPolicy":
        payload = dict(value)
        payload["budget"] = Budget(**payload.get("budget", {}))
        payload["weights"] = SamplingWeights(**payload.get("weights", {}))
        pruning = dict(payload.get("pruning", {}))
        if "prohibited_patterns" in pruning:
            pruning["prohibited_patterns"] = tuple(pruning["prohibited_patterns"])
        payload["pruning"] = PruningRules(**pruning)
        return cls(**payload)


@dataclass
class Candidate:
    """An exploration candidate factor expression."""
    candidate_id: str
    expression: str
    family: str
    fields: List[str]
    operators: List[str] = field(default_factory=list)
    template_id: str = ""
    novelty_score: float = 0.0
    decay: int = 12
    canonical_hash: str = ""
    lineage_parent_id: Optional[str] = None
    generation_strategy: str = "carpet"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def compute_canonical_hash(self) -> str:
        from alpha_operator_framework.domain.ast import to_canonical_string

        canonical = to_canonical_string(self.expression)
        self.canonical_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
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
