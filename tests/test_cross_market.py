"""Unit tests for Cross-Market Robustness and Migration Suite."""

import pytest

from alpha_operator_framework.domain.cross_market import (
    CrossMarketMetrics,
    CrossMarketReport,
    evaluate_cross_market_robustness,
)
from alpha_operator_framework.domain.sandbox.market_data import generate_synthetic_market_data


def test_evaluate_cross_market_robustness():
    # 生成 3 个区域的合成市场数据
    md_usa = generate_synthetic_market_data(n_days=100, n_assets=30, seed=1)
    md_eur = generate_synthetic_market_data(n_days=100, n_assets=30, seed=2)
    md_chn = generate_synthetic_market_data(n_days=100, n_assets=30, seed=3)

    market_dict = {
        "USA": md_usa,
        "EUR": md_eur,
        "CHN": md_chn,
    }

    expr = "rank(close) / (rank(volume) + 0.01)"
    report = evaluate_cross_market_robustness(expr, market_dict, min_universal_sharpe=0.5, min_cmci=0.5)

    assert report.expression == expr
    assert len(report.region_metrics) == 3
    assert "USA" in report.region_metrics
    assert "EUR" in report.region_metrics
    assert "CHN" in report.region_metrics
    assert 0.0 <= report.consistency_score <= 1.0
    assert 0.0 <= report.positive_regions_ratio <= 1.0
