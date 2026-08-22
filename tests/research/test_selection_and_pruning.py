"""Pure selection and pruning policies for ResearchRound."""

from __future__ import annotations

from alpha_operator_framework.research.pruning import AstPrePruner
from alpha_operator_framework.research.round import Candidate, ResearchPolicy


def test_pre_pruning_rejects_ast_equivalent_candidates_with_reason() -> None:
    policy = ResearchPolicy(region="GBR", universe="TOP700", max_backtests=2)
    candidates = [
        Candidate("nested", "rank(rank(close))", "family", ("close",), ("rank",), "template"),
        Candidate("canonical", "rank(close)", "family", ("close",), ("rank",), "template"),
    ]

    decisions = AstPrePruner().evaluate(candidates, policy)

    assert decisions[0].rejected is False
    assert decisions[1].rejected is True
    assert decisions[1].reason_code == "AST_CANONICAL_DUPLICATE"
