from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta

from alpha_operator_framework.domain.pruning_components.correlation import (
    MultiChannelCorrelationConfig,
    multi_channel_correlation_prune,
)
from alpha_operator_framework.research.optimization import (
    CompletedExpression,
    promotion_quality_reason,
)


def _pnl_payload(changes: list[float]) -> dict:
    level = 0.0
    records = []
    start = date(2020, 1, 1)
    for index, change in enumerate(changes):
        level += change
        records.append({"date": str(start + timedelta(days=index)), "pnl": level})
    return {"records": records}


def test_quality_gate_rejects_low_long_short_coverage_but_keeps_legacy_unknowns() -> None:
    low = CompletedExpression("rank(close)", ("close",), 1.5, 1.0, True, long_count=3, short_count=4)
    legacy = CompletedExpression("rank(open)", ("open",), 1.5, 1.0, True)

    assert promotion_quality_reason(low, min_long_short_sum=20) == "long_short_count_too_low"
    assert promotion_quality_reason(legacy, min_long_short_sum=20) is None


def test_quality_gate_does_not_apply_submission_checks_to_construction_promotion() -> None:
    exploratory = CompletedExpression(
        "rank(close)", ("close",), 0.8, 0.5, False,
        long_count=100, short_count=100,
    )

    assert promotion_quality_reason(exploratory, min_long_short_sum=20) is None


def test_multi_channel_pruning_uses_union_and_rejects_flat_pnl() -> None:
    wave = [math.sin(index / 5) for index in range(160)]
    orthogonal = [math.cos(index / 5) for index in range(160)]
    payloads = {
        "a": _pnl_payload(wave),
        "b": _pnl_payload([value * 2 for value in wave]),
        "c": _pnl_payload(orthogonal),
        "flat": _pnl_payload([1.0] * 20 + [0.0] * 140),
    }

    async def fetch(alpha_id: str) -> dict:
        return payloads[alpha_id]

    candidates = [
        {"alpha_id": "a", "alpha_sha": "sha-a", "sharpe": 2.0, "fitness": 2.0, "margin": 8.0},
        {"alpha_id": "b", "alpha_sha": "sha-b", "sharpe": 1.5, "fitness": 1.5, "margin": 7.0},
        {"alpha_id": "c", "alpha_sha": "sha-c", "sharpe": 1.4, "fitness": 1.4, "margin": 6.0},
        {"alpha_id": "flat", "alpha_sha": "sha-flat", "sharpe": 1.3, "fitness": 1.3, "margin": 5.0},
    ]

    kept, pruned = asyncio.run(multi_channel_correlation_prune(
        candidates,
        MultiChannelCorrelationConfig(min_periods=100, max_consecutive_flat_days=100),
        pnl_fetcher=fetch,
    ))

    assert {row["alpha_id"] for row in kept} == {"a", "c"}
    reasons = {row["alpha_id"]: row["prune_reason"] for row in pruned}
    assert reasons == {"b": "multi_channel_corr", "flat": "pnl_flat_run"}


def test_single_candidate_still_runs_pnl_shape_gate() -> None:
    async def fetch(_alpha_id: str) -> dict:
        return _pnl_payload([1.0] * 20 + [0.0] * 140)

    candidates = [
        {"alpha_id": "flat", "alpha_sha": "sha-flat", "sharpe": 2.0,
         "fitness": 2.0, "margin": 8.0},
    ]

    kept, pruned = asyncio.run(multi_channel_correlation_prune(
        candidates,
        MultiChannelCorrelationConfig(min_periods=100, max_consecutive_flat_days=100),
        pnl_fetcher=fetch,
    ))

    assert kept == []
    assert pruned[0]["prune_reason"] == "pnl_flat_run"
