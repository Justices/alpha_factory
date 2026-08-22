"""Unit tests for Pre-Pruning and 2D Consensus Post-Pruning."""

import pytest
from alpha_operator_framework.ddd.domain.candidate_exploration.models import Candidate, ResearchPolicy
from alpha_operator_framework.ddd.domain.candidate_exploration.services import PrePruningService
from alpha_operator_framework.ddd.domain.experiment_governance.models import (
    BacktestTask,
    ExperimentBatch,
    NormalizedBacktestResult,
)
from alpha_operator_framework.ddd.domain.experiment_governance.services import PostBacktestPruner


def test_pre_pruning_service_syntax_and_duplicates():
    service = PrePruningService(prohibited_patterns=["ts_delta(ts_delta("])
    policy = ResearchPolicy()
    seen = set()

    c_valid = Candidate(candidate_id="c1", expression="rank(close)", family="f", fields=["close"])
    c_unbalanced = Candidate(candidate_id="c2", expression="rank(close", family="f", fields=["close"])
    c_prohibited = Candidate(candidate_id="c3", expression="ts_delta(ts_delta(close, 5), 10)", family="f", fields=["close"])
    c_dup = Candidate(candidate_id="c4", expression="rank(close)", family="f", fields=["close"])

    d1 = service.evaluate_candidate(c_valid, seen, policy)
    d2 = service.evaluate_candidate(c_unbalanced, seen, policy)
    d3 = service.evaluate_candidate(c_prohibited, seen, policy)
    d4 = service.evaluate_candidate(c_dup, seen, policy)

    assert d1.is_rejected is False
    assert d2.is_rejected is True and d2.reason_code == "SYNTAX_UNBALANCED_PARENS"
    assert d3.is_rejected is True and d3.reason_code == "PROHIBITED_SYNTAX_PATTERN"
    assert d4.is_rejected is True and d4.reason_code == "EXACT_CANONICAL_DUPLICATE"


def test_post_backtest_pruner_gold_shield():
    pruner = PostBacktestPruner()
    batch = ExperimentBatch(batch_id="b1", idempotency_key="k1")

    # Winning candidate with Sharpe >= 1.0 confers Gold Shield to its skeleton
    r_win = NormalizedBacktestResult("t1", "a1", "ts_scale(group_rank(f1, subindustry), 30)", True, 1.45, 1.2, 0.2, 0.15, 0.05, True)
    # Another test on same skeleton that had low sharpe
    r_low = NormalizedBacktestResult("t2", "a2", "ts_scale(group_rank(f2, subindustry), 30)", True, -0.05, 0.0, 0.2, -0.01, 0.15, True)
    # Defective extreme turnover
    r_churn = NormalizedBacktestResult("t3", "a3", "ts_delta(f3, 1)", True, -0.6, 0.0, 0.85, -0.2, 0.4, True)

    batch.record_result(r_win)
    batch.record_result(r_low)
    batch.record_result(r_churn)

    decisions = pruner.evaluate_batch(batch)
    d_map = {d.task_id: d for d in decisions}

    assert d_map["t1"].is_pruned is False and d_map["t1"].reason_code == "GOLD_SHIELD_IMMUNE"
    assert d_map["t2"].is_pruned is False and d_map["t2"].reason_code == "GOLD_SHIELD_IMMUNE"  # Protected by Gold Shield
    assert d_map["t3"].is_pruned is True and d_map["t3"].reason_code == "EXTREME_NOISE_OR_TURNOVER"
