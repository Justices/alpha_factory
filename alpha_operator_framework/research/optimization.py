"""Pure signal and result-driven pruning decisions for the research loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from alpha_operator_framework.distill.template_abstractor import abstract_template
from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.research.strategy_config import Threshold


SIGNAL_SHARPE = 1.25
SIGNAL_FITNESS = 0.8
MIN_DISTINCT_FIELDS = 3
MIN_SAMPLES = 4
MIN_FAILURE_RATE = 0.80


@dataclass(frozen=True)
class CompletedExpression:
    expression: str
    fields: tuple[str, ...]
    sharpe: float
    fitness: float
    checks_passed: bool
    alpha_sha: str = ""
    family: str = "base"
    origin_strategy: str = ""
    platform_alpha_id: str = ""
    turnover: float = 0.0
    margin: float = 0.0
    pnl: float | None = None
    long_count: int | None = None
    short_count: int | None = None


@dataclass(frozen=True)
class ResultPruneRule:
    pattern: str
    pattern_type: str
    reason: str


def is_signal_parent(result: BacktestResult | CompletedExpression) -> bool:
    """Return whether a result qualifies for one bounded optimization branch."""
    return result.sharpe > SIGNAL_SHARPE and result.fitness > SIGNAL_FITNESS


def promotion_quality_reason(
    result: CompletedExpression,
    *,
    min_long_short_sum: int = 0,
) -> str | None:
    """Return a deterministic construction-quality rejection reason.

    Missing long/short statistics are kept rather than treated as zero because
    legacy rows may not have persisted the fields. New platform results carry
    both values and are checked strictly. Platform submission checks are
    intentionally not evaluated here: exploratory promotion has its own lower
    Sharpe/Fitness gate, while full platform checks remain a submission gate.
    """
    if (
        min_long_short_sum > 0
        and result.long_count is not None
        and result.short_count is not None
        and result.long_count + result.short_count < min_long_short_sum
    ):
        return "long_short_count_too_low"
    return None


def derive_consensus_prune_rules(
    rows: Sequence[CompletedExpression],
    *,
    sharpe_gate: Threshold,
) -> list[ResultPruneRule]:
    """Derive structural rules using the configured promotion Sharpe gate."""
    by_template: dict[str, list[CompletedExpression]] = {}
    for row in rows:
        template = abstract_template(row.expression, row.fields)
        if template != row.expression:
            by_template.setdefault(template, []).append(row)

    rules: list[ResultPruneRule] = []
    seen_patterns: set[tuple[str, str]] = set()
    # Any expression that fails the same Sharpe gate used for construction
    # promotion retires its exact abstract template before another slice is
    # planned. This applies without waiting for the consensus sample size.
    gate_symbol = ">" if sharpe_gate.operator == "gt" else ">="
    gate_reason = f"sharpe fails parent gate ({gate_symbol} {sharpe_gate.value:g})"
    for template, samples in sorted(by_template.items()):
        if any(not sharpe_gate.passes(sample.sharpe) for sample in samples):
            key = (template, "abstract_template")
            if key not in seen_patterns:
                rules.append(ResultPruneRule(template, "abstract_template", gate_reason))
                seen_patterns.add(key)
    for template, samples in sorted(by_template.items()):
        if len(samples) < MIN_SAMPLES or any(is_signal_parent(sample) for sample in samples):
            continue
        fields = {field for sample in samples for field in sample.fields}
        failures = [sample for sample in samples if not sharpe_gate.passes(sample.sharpe)]
        average_sharpe = sum(sample.sharpe for sample in samples) / len(samples)
        if (
            len(fields) >= MIN_DISTINCT_FIELDS
            and len(failures) / len(samples) >= MIN_FAILURE_RATE
            and not sharpe_gate.passes(average_sharpe)
        ):
            prefix = template.split("{", 1)[0]
            key = (prefix, "prefix")
            if prefix and key not in seen_patterns:
                rules.append(ResultPruneRule(prefix, "prefix", "consensus failure"))
                seen_patterns.add(key)
    return rules
