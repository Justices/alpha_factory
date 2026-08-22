"""D-Optimal Diversity Selection Policy."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence
from .base import SelectionPolicy
from ..models import Candidate, ResearchPolicy, SelectionDecision
from ...ports import RandomSource


class DOptimalDiversitySelectionPolicy(SelectionPolicy):
    """Information-theoretic diversity selection maximizing feature-space coverage."""

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

        budget_k = min(len(candidates), policy.budget.max_backtested)
        selected_ids: set[str] = set()
        covered_fields: set[str] = set()
        covered_families: set[str] = set()

        remaining = list(candidates)
        # Greedy D-optimal heuristic: select candidates that maximize orthogonal field & family entropy
        while len(selected_ids) < budget_k and remaining:
            best_cand = None
            best_score = -1.0

            for c in remaining:
                field_novelty = sum(1.0 for f in c.fields if f not in covered_fields)
                family_novelty = 2.0 if c.family not in covered_families else 0.5
                length_penalty = 1.0 / (1.0 + math.log1p(len(c.expression)))
                score = field_novelty * 2.0 + family_novelty + length_penalty + random_source.uniform(0.0, 0.01)

                if score > best_score:
                    best_score = score
                    best_cand = c

            if best_cand:
                selected_ids.add(best_cand.candidate_id)
                covered_fields.update(best_cand.fields)
                covered_families.add(best_cand.family)
                remaining.remove(best_cand)

        for c in candidates:
            is_sel = c.candidate_id in selected_ids
            decisions.append(
                SelectionDecision(
                    candidate_id=c.candidate_id,
                    is_selected=is_sel,
                    score_components={"diversity_entropy": 1.0 if is_sel else 0.0},
                    algorithm="d_optimal_diversity",
                    policy_version=policy.version,
                    seed=getattr(random_source, "seed", 42),
                    reason="Maximal feature-space information gain" if is_sel else "Redundant feature space",
                )
            )

        return decisions
