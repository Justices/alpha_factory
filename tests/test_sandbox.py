"""Unit tests for local vectorized Sandbox Engine."""

import numpy as np
import pytest

from alpha_operator_framework.domain.sandbox import (
    MarketDataCrossSection,
    SandboxEngine,
    generate_synthetic_market_data,
    evaluate_expression_local,
    cs_rank,
    cs_zscore,
    ts_rank,
    ts_delta,
    group_neutralize,
)
from alpha_operator_framework.domain.pruning import sandbox_prefilter
from alpha_operator_framework.domain.families import Task


def test_synthetic_market_data():
    data = generate_synthetic_market_data(n_days=100, n_assets=20, seed=123)
    assert data.shape == (100, 20)
    assert "close" in data.fields
    assert "open" in data.fields
    assert "volume" in data.fields
    assert "industry" in data.fields
    assert data.forward_returns.shape == (100, 20)


def test_vectorized_operators():
    X = np.array([
        [1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0],
        [7.0, 8.0, 9.0],
    ])

    # cs_rank
    ranks = cs_rank(X)
    assert np.allclose(ranks[0], [0.0, 0.5, 1.0])

    # cs_zscore
    zscores = cs_zscore(X)
    assert np.allclose(np.mean(zscores, axis=1), [0.0, 0.0, 0.0])

    # ts_delta
    delta = ts_delta(X, 1)
    assert np.allclose(delta[1], [3.0, 3.0, 3.0])

    # group_neutralize
    groups = np.array([0, 0, 1])
    neut = group_neutralize(X, groups)
    # first two assets in same group should de-mean to zero sum
    assert np.allclose(neut[0, 0] + neut[0, 1], 0.0)


def test_sandbox_engine_evaluation():
    data = generate_synthetic_market_data(n_days=150, n_assets=30, seed=42)
    engine = SandboxEngine(data)

    # 1. Evaluate momentum signal
    metrics1 = engine.evaluate_metrics("ts_delta(close, 20) / close")
    assert metrics1.is_valid
    assert isinstance(metrics1.rank_ic, float)
    assert isinstance(metrics1.sharpe, float)
    assert isinstance(metrics1.turnover, float)
    assert metrics1.coverage > 0.8

    # 2. Evaluate analyst_eps (synthesized with positive predictive power)
    metrics2 = engine.evaluate_metrics("analyst_eps")
    assert metrics2.is_valid
    assert metrics2.rank_ic > 0.0  # Synthetic analyst_eps was generated with positive signal
    assert metrics2.sharpe > 0.0

    # 3. Group neutralize
    metrics3 = engine.evaluate_metrics("group_neutralize(analyst_eps, industry)")
    assert metrics3.is_valid


def test_evaluate_expression_local_convenience():
    metrics = evaluate_expression_local("rank(close) / rank(volume)")
    assert metrics.is_valid
    assert -1.0 <= metrics.rank_ic <= 1.0


def test_sandbox_prefilter():
    data = generate_synthetic_market_data(n_days=100, n_assets=30, seed=42)
    tasks = [
        Task(expression="analyst_eps", template_index=0, family="unary", fields_per_alpha=1),
        Task(expression="rank(close) * 0", template_index=1, family="unary", fields_per_alpha=1), # zero signal
    ]

    passed, rejected = sandbox_prefilter(tasks, market_data=data, min_abs_ic=0.01, min_sharpe=0.1)
    passed_exprs = [t.expression for t in passed]
    rejected_exprs = [t.expression for t in rejected]

    assert "analyst_eps" in passed_exprs
    assert "rank(close) * 0" in rejected_exprs
