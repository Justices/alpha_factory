from alpha_operator_framework.research.optimization import (
    CompletedExpression,
    ResultPruneRule,
    derive_consensus_prune_rules,
    is_signal_parent,
)


def _row(expression: str, fields: tuple[str, ...], sharpe: float, fitness: float, checks_passed: bool = True) -> CompletedExpression:
    return CompletedExpression(expression, fields, sharpe, fitness, checks_passed)


def test_signal_parent_thresholds_are_strict() -> None:
    assert not is_signal_parent(_row("rank(close)", ("close",), 1.25, 0.81))
    assert not is_signal_parent(_row("rank(close)", ("close",), 1.26, 0.8))
    assert is_signal_parent(_row("rank(close)", ("close",), 1.26, 0.81))


def test_consensus_pruning_requires_cross_field_failure_and_gold_shield() -> None:
    failures = [_row(f"rank(f{index})", (f"f{index}",), 0.0, 0.0) for index in range(4)]

    assert derive_consensus_prune_rules(failures) == [ResultPruneRule("rank(", "prefix", "consensus failure")]
    assert derive_consensus_prune_rules([
        *failures,
        _row("rank(winner)", ("winner",), 1.26, 0.81),
    ]) == []
