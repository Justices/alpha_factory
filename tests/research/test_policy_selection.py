"""Versioned selector configuration tests."""

from __future__ import annotations

import random
import json

from alpha_operator_framework.research.policy import PolicySnapshot, build_selector, load_policy
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
