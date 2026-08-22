"""ResearchRound aggregate behavior."""

from __future__ import annotations

import random

from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy, ResearchRound
from alpha_operator_framework.research.selection import WeightedStratifiedSelector


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
