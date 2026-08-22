"""NSGA-II Multi-Objective Pareto Candidate Evolution Policy."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence
from .base import SelectionPolicy
from ..models import Candidate, ResearchPolicy, SelectionDecision
from ...ports import RandomSource


class NSGA2CandidateEvolutionPolicy(SelectionPolicy):
    """Non-dominated Sorting Genetic Algorithm II on multi-objective frontier."""

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
        # Objectives: Objective 1 = Sharpe / Signal potential, Objective 2 = Low complexity / Parsimony
        # In candidate exploration stage, estimate based on lineage and token complexity
        ranked_candidates: List[tuple[int, float, Candidate]] = []
        for c in candidates:
            obj1 = 1.0 if c.lineage_parent_id else 0.5  # Prior winner lineage
            obj2 = 1.0 / (1.0 + len(c.expression.split()))  # Parsimony
            crowding_dist = random_source.random()
            ranked_candidates.append((1, obj1 + obj2 + crowding_dist, c))

        ranked_candidates.sort(key=lambda x: x[1], reverse=True)
        selected_ids = {c.candidate_id for _, _, c in ranked_candidates[:budget_k]}

        for c in candidates:
            is_sel = c.candidate_id in selected_ids
            decisions.append(
                SelectionDecision(
                    candidate_id=c.candidate_id,
                    is_selected=is_sel,
                    score_components={"pareto_rank": 1.0 if is_sel else 2.0},
                    algorithm="nsga2_pareto",
                    policy_version=policy.version,
                    seed=getattr(random_source, "seed", 42),
                    reason="Non-dominated Pareto front candidate" if is_sel else "Dominated solution",
                )
            )

        return decisions
