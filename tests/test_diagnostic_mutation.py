"""Unit tests for Failure Diagnostic Engine and Alpha Mutator."""

import pytest

from alpha_operator_framework.distill.diagnostic import (
    FailureDiagnosis,
    FailureMode,
    diagnose_alpha_failure,
)
from alpha_operator_framework.distill.mutation import (
    AlphaMutator,
    auto_repair_failed_alphas,
)
from alpha_operator_framework.domain.families import Task


def test_diagnose_high_turnover():
    alpha_row = {
        "alpha_id": "alpha_001",
        "expression": "ts_delta(close, 2)",
        "sharpe": 1.40,
        "turnover": 0.85,  # > 0.70
        "fitness": 1.20,
    }
    diag = diagnose_alpha_failure(alpha_row)
    assert diag.primary_cause == FailureMode.HIGH_TURNOVER
    assert diag.is_repairable
    assert any("ts_decay_linear" in r for r in diag.repair_recommendations)


def test_diagnose_negative_sharpe():
    alpha_row = {
        "alpha_id": "alpha_002",
        "expression": "rank(volume) / rank(close)",
        "sharpe": -1.65,  # Strongly negative
        "turnover": 0.20,
    }
    diag = diagnose_alpha_failure(alpha_row)
    assert diag.primary_cause == FailureMode.NEGATIVE_SHARPE
    assert diag.is_repairable
    assert any("invert_sign" in r for r in diag.repair_recommendations)


def test_diagnose_sub_universe_failure():
    alpha_row = {
        "alpha_id": "alpha_003",
        "expression": "ts_rank(close, 22)",
        "sharpe": 1.35,
        "turnover": 0.25,
    }
    checks = [
        {"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "FAIL", "value": 0.4},
    ]
    diag = diagnose_alpha_failure(alpha_row, checks=checks)
    assert diag.primary_cause == FailureMode.LOW_SUB_UNIVERSE_SHARPE
    assert diag.is_repairable


def test_alpha_mutator_high_turnover_smoothing():
    mutator = AlphaMutator()
    task = Task(
        expression="ts_delta(close, 5)",
        template_index=0,
        family="unary",
        fields_per_alpha=1,
    )
    diag = FailureDiagnosis(
        alpha_id="alpha_001",
        expression=task.expression,
        primary_cause=FailureMode.HIGH_TURNOVER,
    )

    mutated_tasks = mutator.mutate_task(task, diag, max_candidates=3)
    assert len(mutated_tasks) > 0

    mutated_exprs = [t.expression for t in mutated_tasks]
    # Check that ts_decay_linear or ts_mean or rank was injected
    assert any("ts_decay_linear" in e or "ts_mean" in e or "rank" in e for e in mutated_exprs)


def test_alpha_mutator_negative_sharpe_inversion():
    mutator = AlphaMutator()
    task = Task(
        expression="rank(close) - rank(volume)",
        template_index=0,
        family="binary",
        fields_per_alpha=2,
    )
    diag = FailureDiagnosis(
        alpha_id="alpha_002",
        expression=task.expression,
        primary_cause=FailureMode.NEGATIVE_SHARPE,
    )

    mutated_tasks = mutator.mutate_task(task, diag, max_candidates=2)
    assert len(mutated_tasks) > 0
    mutated_exprs = [t.expression for t in mutated_tasks]
    assert any("-1.0" in e or "reverse" in e for e in mutated_exprs)


def test_auto_repair_failed_alphas_batch():
    failed_rows = [
        {"alpha_id": "a1", "expression": "ts_delta(close, 3)", "turnover": 0.90, "sharpe": 1.4},
        {"alpha_id": "a2", "expression": "rank(volume)", "turnover": 0.20, "sharpe": -1.5},
    ]

    repaired = auto_repair_failed_alphas(failed_rows, max_mutations_per_alpha=2)
    assert len(repaired) >= 2
    for t in repaired:
        assert "mutation_" in t.expression_origin
