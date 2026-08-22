"""Thompson & UCB Multi-Armed Bandit Combinatorial Exploration Policy."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence
from .base import SelectionPolicy
from ..models import Candidate, ResearchPolicy, SelectionDecision
from ...ports import RandomSource


class ThompsonCombinatorialSelectionPolicy(SelectionPolicy):
    """Bayesian Thompson Sampling balancing exploration and exploitation on operator/field combinations."""

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
        scores: List[tuple[float, Candidate]] = []

        knowledge_scores = context_knowledge if isinstance(context_knowledge, dict) else {}

        for c in candidates:
            # Prior: alpha=1, beta=1 -> Beta distribution sample
            prior_success = knowledge_scores.get(c.family, {}).get("successes", 1.0)
            prior_failures = knowledge_scores.get(c.family, {}).get("failures", 1.0)

            # Approximation of beta sample using random_source
            u1 = max(1e-6, random_source.random())
            u2 = max(1e-6, random_source.random())
            sample_val = (prior_success / (prior_success + prior_failures)) + 0.2 * (u1 - u2)
            scores.append((sample_val, c))

        # Sort descending
        scores.sort(key=lambda x: x[0], reverse=True)
        selected_ids = {c.candidate_id for _, c in scores[:budget_k]}

        for c in candidates:
            is_sel = c.candidate_id in selected_ids
            decisions.append(
                SelectionDecision(
                    candidate_id=c.candidate_id,
                    is_selected=is_sel,
                    score_components={"thompson_sample": 1.0 if is_sel else 0.0},
                    algorithm="thompson_combinatorial",
                    policy_version=policy.version,
                    seed=getattr(random_source, "seed", 42),
                    reason="High posterior Thompson sample" if is_sel else "Lower posterior expected reward",
                )
            )

        return decisions


class UCBCombinatorialSelectionPolicy(SelectionPolicy):
    """Upper Confidence Bound (UCB1) exploration policy."""

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
        total_trials = max(10, len(candidates))
        scores: List[tuple[float, Candidate]] = []

        knowledge_scores = context_knowledge if isinstance(context_knowledge, dict) else {}

        for c in candidates:
            fam_stats = knowledge_scores.get(c.family, {})
            n_pulls = max(1, fam_stats.get("trials", 1))
            mean_reward = fam_stats.get("avg_sharpe", 0.0)
            # UCB exploration term
            exploration = math.sqrt(2.0 * math.log(total_trials) / n_pulls)
            ucb_score = mean_reward + exploration + random_source.uniform(0.0, 0.01)
            scores.append((ucb_score, c))

        scores.sort(key=lambda x: x[0], reverse=True)
        selected_ids = {c.candidate_id for _, c in scores[:budget_k]}

        for c in candidates:
            is_sel = c.candidate_id in selected_ids
            decisions.append(
                SelectionDecision(
                    candidate_id=c.candidate_id,
                    is_selected=is_sel,
                    score_components={"ucb_score": 1.0 if is_sel else 0.0},
                    algorithm="ucb_combinatorial",
                    policy_version=policy.version,
                    seed=getattr(random_source, "seed", 42),
                    reason="Upper confidence bound frontier" if is_sel else "Suboptimal confidence bound",
                )
            )

        return decisions
