"""Weighted Stratified Random Selection Policy (Baseline & Cold-Start)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence
from .base import SelectionPolicy
from ..models import Candidate, ResearchPolicy, SelectionDecision
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

        # Group by family
        by_family: Dict[str, List[Candidate]] = defaultdict(list)
        for c in candidates:
            by_family[c.family].append(c)

        target_per_family = max(1, policy.budget.max_backtested // max(1, len(by_family)))
        selected_candidates: List[Candidate] = []

        for fam, fam_cands in by_family.items():
            quota = policy.family_quotas.get(fam, target_per_family)
            if len(fam_cands) <= quota:
                sampled = list(fam_cands)
            else:
                sampled = random_source.sample(fam_cands, quota)
            selected_candidates.extend(sampled)

        # Enforce hard budget
        if len(selected_candidates) > policy.budget.max_backtested:
            selected_candidates = random_source.sample(selected_candidates, policy.budget.max_backtested)

        selected_ids = {c.candidate_id for c in selected_candidates}

        for c in candidates:
            is_sel = c.candidate_id in selected_ids
            decisions.append(
                SelectionDecision(
                    candidate_id=c.candidate_id,
                    is_selected=is_sel,
                    score_components={"stratified_weight": 1.0 if is_sel else 0.0},
                    algorithm="weighted_stratified",
                    policy_version=policy.version,
                    seed=getattr(random_source, "seed", 42),
                    reason="Stratified family quota match" if is_sel else "Exceeded family quota",
                )
            )

        return decisions
