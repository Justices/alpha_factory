from alpha_operator_framework.research.optimization import (
    CompletedExpression,
    ResultPruneRule,
    derive_consensus_prune_rules,
    is_signal_parent,
)
from alpha_operator_framework.distill.template_pruner import matches_prune_rule
from alpha_operator_framework.research.strategy_config import Threshold


PROMOTION_SHARPE_GATE = Threshold("gt", 0.6)


def _row(expression: str, fields: tuple[str, ...], sharpe: float, fitness: float, checks_passed: bool = True) -> CompletedExpression:
    return CompletedExpression(expression, fields, sharpe, fitness, checks_passed)


def test_signal_parent_thresholds_are_strict() -> None:
    assert not is_signal_parent(_row("rank(close)", ("close",), 1.25, 0.81))
    assert not is_signal_parent(_row("rank(close)", ("close",), 1.26, 0.8))
    assert is_signal_parent(_row("rank(close)", ("close",), 1.26, 0.81))


def test_low_sharpe_template_is_pruned_without_waiting_for_consensus() -> None:
    failures = [_row(f"rank(f{index})", (f"f{index}",), 0.0, 0.0) for index in range(4)]

    assert derive_consensus_prune_rules(failures, sharpe_gate=PROMOTION_SHARPE_GATE) == [
        ResultPruneRule("rank({a})", "abstract_template", "sharpe fails parent gate (> 0.6)"),
        ResultPruneRule("rank(", "prefix", "consensus failure"),
    ]
    assert derive_consensus_prune_rules([
        *failures,
        _row("rank(winner)", ("winner",), 1.26, 0.81),
    ], sharpe_gate=PROMOTION_SHARPE_GATE) == [
        ResultPruneRule("rank({a})", "abstract_template", "sharpe fails parent gate (> 0.6)"),
    ]


def test_consensus_pruning_uses_configured_strict_promotion_sharpe_gate() -> None:
    below_cutoff = [
        _row(f"rank(f{index})", (f"f{index}",), 0.59, 0.9)
        for index in range(4)
    ]
    at_cutoff = [
        _row(f"rank(f{index})", (f"f{index}",), 0.6, 0.9)
        for index in range(4)
    ]
    above_cutoff = [
        _row(f"rank(f{index})", (f"f{index}",), 0.61, 0.9)
        for index in range(4)
    ]

    expected = [
        ResultPruneRule("rank({a})", "abstract_template", "sharpe fails parent gate (> 0.6)"),
        ResultPruneRule("rank(", "prefix", "consensus failure")
    ]
    assert derive_consensus_prune_rules(
        below_cutoff, sharpe_gate=PROMOTION_SHARPE_GATE,
    ) == expected
    assert derive_consensus_prune_rules(
        at_cutoff, sharpe_gate=PROMOTION_SHARPE_GATE,
    ) == expected
    assert derive_consensus_prune_rules(
        above_cutoff, sharpe_gate=PROMOTION_SHARPE_GATE,
    ) == []


def test_abstract_template_rule_only_matches_the_same_field_shape() -> None:
    rule = {"pattern": "rank({a})", "pattern_type": "abstract_template"}

    assert matches_prune_rule("rank(volume)", rule, fields=("volume",))
    assert not matches_prune_rule("rank(ts_mean(volume, 5))", rule, fields=("volume",))
