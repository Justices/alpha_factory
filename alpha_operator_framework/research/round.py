"""Pure domain types for deciding one research round's backtest cohort."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


class SelectionPolicy(Protocol):
    def select(
        self,
        candidates: Sequence["Candidate"],
        policy: "ResearchPolicy",
        knowledge: "KnowledgeSnapshot",
        random_source: Any,
    ) -> list["SelectionDecision"]: ...


@dataclass(frozen=True)
class ResearchPolicy:
    region: str
    universe: str
    max_backtests: int
    field_weight: float = 1.0
    operator_weight: float = 1.0
    template_weight: float = 1.0
    novelty_weight: float = 1.0
    uncertainty_weight: float = 1.0
    family_quotas: Mapping[str, int] = field(default_factory=dict)
    prohibited_patterns: tuple[str, ...] = ()
    policy_version: str = "default"
    selection_strategy: str = "weighted_stratified"
    min_sharpe: float = 1.0
    min_fitness: float = 0.8
    min_margin: float = 4.0
    max_turnover: float = 0.70
    delay: int = 1
    decay: int = 8
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    expression: str
    family: str
    fields: tuple[str, ...]
    operators: tuple[str, ...]
    template_id: str
    novelty_score: float = 0.0
    lineage_parent_id: str | None = None


@dataclass(frozen=True)
class KnowledgeSnapshot:
    version: int
    field_scores: Mapping[str, float] = field(default_factory=dict)
    operator_scores: Mapping[str, float] = field(default_factory=dict)
    template_scores: Mapping[str, float] = field(default_factory=dict)
    rejected_templates: tuple[str, ...] = ()
    field_trials: Mapping[str, int] = field(default_factory=dict)

    @staticmethod
    def _mean(scores: Mapping[str, float], keys: Sequence[str]) -> float:
        values = [float(scores.get(key, 0.0)) for key in keys]
        return sum(values) / len(values) if values else 0.0

    def field_score(self, candidate: Candidate) -> float:
        return self._mean(self.field_scores, candidate.fields)

    def operator_score(self, candidate: Candidate) -> float:
        return self._mean(self.operator_scores, candidate.operators)

    def template_score(self, candidate: Candidate) -> float:
        return float(self.template_scores.get(candidate.template_id, 0.0))

    def uncertainty(self, candidate: Candidate) -> float:
        trials = sum(int(self.field_trials.get(field, 0)) for field in candidate.fields)
        return 1.0 / (1.0 + trials)

    def rejects(self, candidate: Candidate) -> bool:
        return candidate.template_id in self.rejected_templates


@dataclass(frozen=True)
class SelectionDecision:
    candidate_id: str
    selected: bool
    score_components: Mapping[str, float]
    reason: str
    policy_name: str


@dataclass(frozen=True)
class PruningDecision:
    candidate_id: str
    rejected: bool
    reason_code: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ResearchRound:
    round_id: str
    policy: ResearchPolicy
    seed: int
    candidates: list[Candidate]
    selection_decisions: list[SelectionDecision] = field(default_factory=list)
    pruning_decisions: list[PruningDecision] = field(default_factory=list)

    def select(
        self,
        selector: SelectionPolicy,
        knowledge: KnowledgeSnapshot,
        random_source: Any,
    ) -> list[SelectionDecision]:
        self.selection_decisions = selector.select(self.candidates, self.policy, knowledge, random_source)
        return self.selection_decisions
