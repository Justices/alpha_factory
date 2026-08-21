"""Unit tests for A/B Branch Comparison, baseline verification, and production mode safety."""

import pytest

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.engine import EventSourcedResearchEngine
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.policy import ResearchPolicy, ValidationPartitions


def test_engine_production_mode_safety():
    """测试生产模式 (production=True) 强制持久化存储与平台网关."""
    mem_store = EventStore()
    art_store = ArtifactStore()

    # 1. 内存存储在生产模式下直接被拦截
    with pytest.raises(ValueError, match="必须使用持久化 EventStore"):
        EventSourcedResearchEngine(
            event_store=mem_store,
            artifact_store=art_store,
            production=True,
        )


def test_ab_comparison_fail_closed_on_partition_mismatch():
    """测试当两个分支的分区基线不一致时，A/B 对照器 Fail-Closed 抛出异常."""
    engine = EventSourcedResearchEngine()

    policy_a = ResearchPolicy(
        policy_id="pol_a",
        validation=ValidationPartitions(
            discovery_is="2015-01-01/2019-12-31",
            validation="2020-01-01/2021-12-31",
            locked_oos="2022-01-01/2024-12-31",
        ),
    )
    policy_b = ResearchPolicy(
        policy_id="pol_b",
        validation=ValidationPartitions(
            discovery_is="2016-01-01/2020-12-31",  # 分区不一致!
            validation="2021-01-01/2022-12-31",
            locked_oos="2023-01-01/2024-12-31",
        ),
    )

    graph_a = engine.create_experiment(policy_a)
    graph_b = engine.create_experiment(policy_b)

    engine.plan_and_simulate(graph_a, policy_a, [{"expression": "rank(returns)", "family": "f1"}])
    engine.plan_and_simulate(graph_b, policy_b, [{"expression": "rank(vwap)", "family": "f2"}])

    # 校验基线不匹配必须抛出 ValueError
    with pytest.raises(ValueError, match="基线不匹配"):
        engine.compare_branches(graph_a.graph_id, graph_b.graph_id)


def test_ab_comparison_scientific_yield_and_diversity():
    """测试基于单位预算合格因子产出率与因子族多样性的科学判胜机制."""
    engine = EventSourcedResearchEngine()

    same_val = ValidationPartitions(
        discovery_is="2015-01-01/2019-12-31",
        validation="2020-01-01/2021-12-31",
        locked_oos="2022-01-01/2024-12-31",
    )
    policy_a = ResearchPolicy(policy_id="pol_a", validation=same_val)
    policy_b = ResearchPolicy(policy_id="pol_b", validation=same_val)

    graph_a = engine.create_experiment(policy_a)
    graph_b = engine.create_experiment(policy_b)

    cands_a = [
        {"expression": "rank(returns)", "family": "momentum"},
        {"expression": "ts_rank(returns, 22)", "family": "momentum"},
    ]
    cands_b = [
        {"expression": "ts_delta(returns, 5)", "family": "reversion"},
        {"expression": "reverse(rank(returns))", "family": "mean_reversion"},
    ]

    engine.plan_and_simulate(graph_a, policy_a, cands_a)
    engine.plan_and_simulate(graph_b, policy_b, cands_b)

    report = engine.compare_branches(graph_a.graph_id, graph_b.graph_id)

    assert "validation_baseline" in report
    assert report["validation_baseline"]["partition_verified"] is True
    assert "branch_a" in report
    assert "branch_b" in report
    assert "winner" in report
    assert "yield_per_budget" in report["branch_a"]
