"""Weighted Stratified Random Selection Policy (Baseline & Cold-Start)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence
from .base import SelectionPolicy
from ..models import Candidate, ResearchPolicy, SelectionDecision, SelectionKnowledgeSnapshot
from ...ports import RandomSource


class WeightedStratifiedSelectionPolicy(SelectionPolicy):
    """Samples candidates preserving 10-family structural quotas and field-fairness."""

    def select(
        self,
        candidates: Sequence[Candidate],
        policy: ResearchPolicy,
        random_source: RandomSource,
        context_knowledge: Any = None,
    ) -> List[SelectionDecision]:
        decisions: List[SelectionDecision] = []
        if not candidates:
            return decisions

        knowledge = context_knowledge if isinstance(context_knowledge, SelectionKnowledgeSnapshot) else SelectionKnowledgeSnapshot()

        # Group non-pruned candidates by family.
        by_family: Dict[str, List[Candidate]] = defaultdict(list)
        rejected_ids: set[str] = set()
        for c in candidates:
            if knowledge.rejects(c):
                rejected_ids.add(c.candidate_id)
            else:
                by_family[c.family].append(c)

        target_per_family = max(1, policy.budget.max_backtested // max(1, len(by_family)))
        selected_candidates: List[Candidate] = []

        for fam, fam_cands in by_family.items():
            quota = policy.family_quotas.get(fam, target_per_family)
            scored = sorted(
                ((self._score(candidate, policy, knowledge), candidate) for candidate in fam_cands),
                key=lambda pair: (-pair[0], pair[1].candidate_id),
            )
            selected_candidates.extend(candidate for _, candidate in scored[:quota])

        # Enforce hard budget
        if len(selected_candidates) > policy.budget.max_backtested:
            selected_candidates = random_source.sample(selected_candidates, policy.budget.max_backtested)

        selected_ids = {c.candidate_id for c in selected_candidates}

        for c in candidates:
            is_sel = c.candidate_id in selected_ids
            components = self._components(c, policy, knowledge)
            if c.candidate_id in rejected_ids:
                reason = "Rejected by distilled prune rule"
            elif is_sel:
                reason = "Highest weighted score within family quota"
            else:
                reason = "Exceeded weighted family quota"
            decisions.append(
                SelectionDecision(
                    candidate_id=c.candidate_id,
                    is_selected=is_sel,
                    score_components=components,
                    algorithm="weighted_stratified",
                    policy_version=policy.version,
                    seed=getattr(random_source, "seed", 42),
                    reason=reason,
                )
            )

        return decisions

    @staticmethod
    def _components(
        candidate: Candidate,
        policy: ResearchPolicy,
        knowledge: SelectionKnowledgeSnapshot,
    ) -> Dict[str, float]:
        return {
            "field": policy.weights.field * knowledge.field_score(candidate.fields),
            "operator": policy.weights.operator * knowledge.operator_score(candidate.operators),
            "template": policy.weights.template * knowledge.template_score(candidate.template_id),
            "novelty": policy.weights.novelty * candidate.novelty_score,
            "uncertainty": policy.weights.uncertainty * knowledge.uncertainty(candidate),
        }

    @classmethod
    def _score(
        cls,
        candidate: Candidate,
        policy: ResearchPolicy,
        knowledge: SelectionKnowledgeSnapshot,
    ) -> float:
        return sum(cls._components(candidate, policy, knowledge).values())
