"""Unit tests for Gram-Schmidt orthogonalization and Super-Alpha 2.0 (HRP)."""

import numpy as np
import pytest

from alpha_operator_framework.domain.orthogonalization import (
    build_orthogonal_expression,
    compute_projection_beta,
    gram_schmidt_residualize,
)
from alpha_operator_framework.generation.portfolio import (
    PortfolioMethod,
    build_super_alpha_2,
    compute_hrp_weights,
    compute_inverse_volatility_weights,
)


def test_gram_schmidt_residualize():
    rng = np.random.default_rng(42)
    T = 100
    N = 20

    base_signal = rng.normal(0, 1, size=(T, N))
    # 构造高度共线性的候选信号 candidate = 2.0 * base + noise
    noise = rng.normal(0, 0.2, size=(T, N))
    candidate = 2.0 * base_signal + noise

    # 1. 验证投影 beta 接近 2.0
    beta = compute_projection_beta(candidate, base_signal)
    assert abs(beta - 2.0) < 0.1

    # 2. 执行正交残差化
    residual = gram_schmidt_residualize(candidate, [base_signal])

    # 3. 验证残差与基底的内积/相关性几乎为 0
    inner_prod = np.sum(residual * base_signal)
    norm_base = np.sqrt(np.sum(base_signal ** 2))
    norm_res = np.sqrt(np.sum(residual ** 2))
    cos_sim = abs(inner_prod / (norm_base * norm_res))

    assert cos_sim < 1e-5, f"Expected orthogonality, got cosine similarity {cos_sim}"


def test_build_orthogonal_expression():
    expr = build_orthogonal_expression("rank(close)", "rank(volume)", beta=1.5)
    assert "close" in expr
    assert "volume" in expr
    assert "1.5" in expr


def test_compute_hrp_weights():
    rng = np.random.default_rng(42)
    T = 252
    M = 4

    # 构造不同波动率与相关性的收益矩阵
    returns = rng.normal(0.001, [0.01, 0.02, 0.015, 0.03], size=(T, M))

    weights = compute_hrp_weights(returns)

    assert len(weights) == M
    assert abs(np.sum(weights) - 1.0) < 1e-6
    assert np.all(weights >= 0.0)
    # 低波动资产资产 0 应该获得更高权重
    assert weights[0] > weights[3]


def test_build_super_alpha_2():
    rng = np.random.default_rng(42)
    T = 252
    M = 3
    returns = rng.normal(0.001, 0.01, size=(T, M))

    alphas = [
        {"alpha_id": "a1", "expression": "rank(close)", "turnover": 0.20},
        {"alpha_id": "a2", "expression": "ts_rank(volume, 10)", "turnover": 0.30},
        {"alpha_id": "a3", "expression": "group_neutralize(open, industry)", "turnover": 0.15},
    ]

    super_alpha = build_super_alpha_2(alphas, returns, method=PortfolioMethod.HRP)

    assert super_alpha.composite_expression != ""
    assert len(super_alpha.weights) == 3
    assert super_alpha.expected_sharpe > 0.0
    assert "close" in super_alpha.composite_expression
