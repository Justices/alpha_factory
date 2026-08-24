"""Deterministic offline comparison reports for selection strategies."""

from __future__ import annotations

import random
from typing import Sequence

from .policy import build_selector
from .round import Candidate, KnowledgeSnapshot, ResearchPolicy


def compare_selection_strategies(
    candidates: Sequence[Candidate], policy: ResearchPolicy, knowledge: KnowledgeSnapshot,
    *, seed: int, strategies: Sequence[str],
) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    for strategy in strategies:
        variant = ResearchPolicy(**{**policy.__dict__, "selection_strategy": strategy})
        decisions = build_selector(variant).select(candidates, variant, knowledge, random.Random(seed))
        report[strategy] = {
            "policy_version": variant.policy_version,
            "seed": seed,
            "quota": variant.max_backtests,
            "selected_ids": [item.candidate_id for item in decisions if item.selected],
            "decisions": [item.__dict__ for item in decisions],
        }
    return report
