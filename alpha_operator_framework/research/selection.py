"""Pure first-round selection policies."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from .round import Candidate, KnowledgeSnapshot, ResearchPolicy, SelectionDecision


class WeightedStratifiedSelector:
    """Select the highest evidence-weighted candidates within structural quotas."""

    name = "weighted_stratified"

    def select(
        self,
        candidates: Sequence[Candidate],
        policy: ResearchPolicy,
        knowledge: KnowledgeSnapshot,
        random_source: Any,
    ) -> list[SelectionDecision]:
        grouped: dict[str, list[Candidate]] = defaultdict(list)
        rejected_ids: set[str] = set()
        for candidate in candidates:
            if knowledge.rejects(candidate):
                rejected_ids.add(candidate.candidate_id)
            else:
                grouped[candidate.family].append(candidate)

        selected_ids: set[str] = set()
        per_family = max(1, policy.max_backtests // max(1, len(grouped)))
        for family, members in grouped.items():
            quota = policy.family_quotas.get(family, per_family)
            ranked = sorted(members, key=lambda candidate: (-self.score(candidate, policy, knowledge), candidate.candidate_id))
            selected_ids.update(candidate.candidate_id for candidate in ranked[:quota])

        if len(selected_ids) > policy.max_backtests:
            ranked_all = sorted(
                (candidate for candidate in candidates if candidate.candidate_id in selected_ids),
                key=lambda candidate: (-self.score(candidate, policy, knowledge), candidate.candidate_id),
            )
            selected_ids = {candidate.candidate_id for candidate in ranked_all[:policy.max_backtests]}

        return [
            SelectionDecision(
                candidate_id=candidate.candidate_id,
                selected=candidate.candidate_id in selected_ids,
                score_components=self.components(candidate, policy, knowledge),
                reason=(
                    "Rejected by knowledge pruning rule" if candidate.candidate_id in rejected_ids
                    else "Highest weighted score within family quota" if candidate.candidate_id in selected_ids
                    else "Below weighted family quota"
                ),
                policy_name=self.name,
            )
            for candidate in candidates
        ]

    @staticmethod
    def components(candidate: Candidate, policy: ResearchPolicy, knowledge: KnowledgeSnapshot) -> dict[str, float]:
        return {
            "field": policy.field_weight * knowledge.field_score(candidate),
            "operator": policy.operator_weight * knowledge.operator_score(candidate),
            "template": policy.template_weight * knowledge.template_score(candidate),
            "novelty": policy.novelty_weight * candidate.novelty_score,
            "uncertainty": policy.uncertainty_weight * knowledge.uncertainty(candidate),
        }

    @classmethod
    def score(cls, candidate: Candidate, policy: ResearchPolicy, knowledge: KnowledgeSnapshot) -> float:
        return sum(cls.components(candidate, policy, knowledge).values())
