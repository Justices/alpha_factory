"""ResearchRound aggregate behavior."""

from __future__ import annotations

import random

import pytest

from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy, ResearchRound
from alpha_operator_framework.research.selection import DiversitySelector, WeightedStratifiedSelector


def _round(seed: int) -> ResearchRound:
    policy = ResearchPolicy(
        region="GBR",
        universe="TOP700",
        max_backtests=1,
        field_weight=1.0,
        operator_weight=1.0,
        template_weight=1.0,
    )
    return ResearchRound(
        round_id="round-1",
        policy=policy,
        seed=seed,
        candidates=[
            Candidate("weak", "rank(weak)", "family", ("weak",), ("rank",), "weak-template"),
            Candidate("strong", "rank(strong)", "family", ("strong",), ("rank",), "strong-template"),
        ],
    )


def test_research_round_replays_same_selection_for_same_snapshots_and_seed() -> None:
    snapshot = KnowledgeSnapshot(
        version=3,
        field_scores={"weak": -2.0, "strong": 2.0},
        operator_scores={"rank": 1.0},
        template_scores={"weak-template": -1.0, "strong-template": 1.0},
    )

    first = _round(7).select(WeightedStratifiedSelector(), snapshot, random.Random(7))
    second = _round(7).select(WeightedStratifiedSelector(), snapshot, random.Random(7))

    assert first == second
    assert [d.candidate_id for d in first if d.selected] == ["strong"]
    assert first[1].score_components["field"] > first[0].score_components["field"]


def test_explicit_family_quotas_are_not_clipped_by_a_global_budget() -> None:
    policy = ResearchPolicy(
        region="GBR", universe="TOP700", max_backtests=8,
        family_quotas={"first": 20, "second": 20},
    )
    candidates = [
        Candidate(f"first-{index}", f"rank(first_{index})", "first", (f"first_{index}",), ("rank",), "first")
        for index in range(20)
    ] + [
        Candidate(f"second-{index}", f"rank(second_{index})", "second", (f"second_{index}",), ("rank",), "second")
        for index in range(20)
    ]

    decisions = WeightedStratifiedSelector().select(candidates, policy, KnowledgeSnapshot(version=0), random.Random(7))

    assert sum(decision.selected for decision in decisions) == 40


@pytest.mark.parametrize("selector", [WeightedStratifiedSelector(), DiversitySelector()])
def test_implicit_family_budget_distributes_remainder_and_fills_batch(selector) -> None:
    candidates = [
        Candidate(
            f"{family}-{index}", f"rank({family}_{index})", family,
            (f"{family}_{index}",), ("rank",), "rank",
        )
        for family in ("a", "b", "c")
        for index in range(4)
    ]
    policy = ResearchPolicy("GBR", "TOP700", 8)

    decisions = selector.select(
        candidates, policy, KnowledgeSnapshot(version=0), random.Random(7),
    )

    assert sum(decision.selected for decision in decisions) == 8
