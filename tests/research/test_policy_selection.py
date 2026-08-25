"""Versioned selector configuration tests."""

from __future__ import annotations

import random
import json
import pytest

from alpha_operator_framework.research.policy import PolicySnapshot, build_selector, load_policy, validate_cli_policy_overrides
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot


def test_policy_snapshot_builds_configured_ucb_selector() -> None:
    policy = PolicySnapshot.from_mapping({
        "version": "experiment-7", "region": "GBR", "universe": "TOP700",
        "max_backtests": 1, "selection_strategy": "ucb",
    }).to_research_policy()
    candidates = [
        Candidate("seen", "rank(returns)", "family", ("returns",), ("rank",), "t"),
        Candidate("new", "rank(volume)", "family", ("volume",), ("rank",), "t"),
    ]

    decisions = build_selector(policy).select(
        candidates, policy, KnowledgeSnapshot(version=1, field_scores={"returns": 1.0}, field_trials={"returns": 100}), random.Random(7),
    )

    assert policy.policy_version == "experiment-7"
    assert [item.candidate_id for item in decisions if item.selected] == ["new"]
    assert all(item.policy_name == "ucb" for item in decisions)


def test_load_policy_reads_versioned_json_configuration(tmp_path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"version": "p2", "region": "GBR", "universe": "TOP700", "max_backtests": 3, "selection_strategy": "thompson"}), encoding="utf-8")

    policy = load_policy(path).to_research_policy()

    assert (policy.policy_version, policy.selection_strategy, policy.max_backtests) == ("p2", "thompson", 3)


def test_load_policy_reads_versioned_yaml_configuration(tmp_path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("version: p3\nregion: GBR\nuniverse: TOP700\nmax_backtests: 4\nselection_strategy: diversity\n", encoding="utf-8")

    policy = load_policy(path).to_research_policy()

    assert (policy.policy_version, policy.selection_strategy, policy.max_backtests) == ("p3", "diversity", 4)


def test_policy_rejects_unknown_selector_and_nonpositive_budget() -> None:
    with pytest.raises(ValueError, match="selection_strategy"):
        PolicySnapshot.from_mapping({"region": "GBR", "universe": "TOP700", "max_backtests": 1, "selection_strategy": "unknown"})
    with pytest.raises(ValueError, match="max_backtests"):
        PolicySnapshot.from_mapping({"region": "GBR", "universe": "TOP700", "max_backtests": 0})


def test_policy_validates_nested_weights_templates_pruning_and_evaluation() -> None:
    snapshot = PolicySnapshot.from_mapping({
        "region": "GBR", "universe": "TOP700", "max_backtests": 2,
        "weights": {"field": 2.0, "operator": 1.5},
        "templates": ["rank_field", "ts_rank_22"],
        "pruning": {"prohibited_patterns": ["group_rank("]},
        "evaluation": {"min_sharpe": 1.2, "min_fitness": 0.9, "min_margin": 4.5, "max_turnover": 0.6},
    })

    policy = snapshot.to_research_policy()

    assert policy.field_weight == 2.0
    assert policy.prohibited_patterns == ("group_rank(",)
    assert policy.min_sharpe == 1.2
    assert snapshot.templates == ("rank_field", "ts_rank_22")


def test_policy_settings_are_applied_to_experiment_tasks() -> None:
    policy = PolicySnapshot.from_mapping({
        "region": "GBR", "universe": "TOP700", "max_backtests": 2,
        "settings": {"delay": 0, "decay": 15, "neutralization": "INDUSTRY", "truncation": 0.05},
    }).to_research_policy()

    assert (policy.delay, policy.decay, policy.neutralization, policy.truncation) == (0, 15, "INDUSTRY", 0.05)


def test_policy_parses_declarative_construction_templates() -> None:
    snapshot = PolicySnapshot.from_mapping({
        "region": "GBR", "universe": "TOP700", "max_backtests": 1,
        "templates": [{"id": "rank_field", "expression": "rank({field})", "family": "cross_sectional", "operators": ["rank"]}],
    })

    templates = snapshot.construction_templates()

    assert templates[0].template_id == "rank_field"
    assert templates[0].expression_template == "rank({field})"


def test_policy_parses_template_promotion_thresholds() -> None:
    snapshot = PolicySnapshot.from_mapping({
        "region": "GBR", "universe": "TOP700", "max_backtests": 1,
        "template_promotion": {"min_support": 3, "min_sharpe": 1.2, "min_fitness": 0.9, "max_correlation": 0.7, "observation_window": 2},
    })

    policy = snapshot.to_research_policy()

    assert (policy.template_min_support, policy.template_observation_window) == (3, 2)


def test_policy_file_rejects_conflicting_explicit_cli_override() -> None:
    policy = PolicySnapshot.from_mapping({
        "region": "GBR", "universe": "TOP700", "max_backtests": 2,
        "settings": {"decay": 15},
    }).to_research_policy()

    with pytest.raises(ValueError, match="decay"):
        validate_cli_policy_overrides(policy, {"decay": 12})


def test_policy_file_parses_retry_configuration(tmp_path) -> None:
    path = tmp_path / "retry-policy.json"
    path.write_text(json.dumps({
        "region": "GBR", "universe": "TOP700", "max_backtests": 2,
        "retry": {"max_attempts": 5, "backoff_seconds": [2, 4.5, 9]},
    }), encoding="utf-8")

    policy = load_policy(path).to_research_policy()

    assert policy.max_retry_attempts == 5
    assert policy.retry_backoff_seconds == (2.0, 4.5, 9.0)


@pytest.mark.parametrize("retry", [
    {"unknown": 1},
    {"max_attempts": 0},
    {"max_attempts": True},
    {"backoff_seconds": []},
    {"backoff_seconds": [1, 0]},
    {"backoff_seconds": "1,2"},
])
def test_policy_rejects_invalid_retry_configuration(retry) -> None:
    with pytest.raises(ValueError, match="retry"):
        PolicySnapshot.from_mapping({
            "region": "GBR", "universe": "TOP700", "max_backtests": 2, "retry": retry,
        })
