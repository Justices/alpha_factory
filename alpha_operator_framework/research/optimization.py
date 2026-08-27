"""Pure signal and result-driven pruning decisions for the research loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from alpha_operator_framework.distill.template_abstractor import abstract_template
from alpha_operator_framework.experiment.models import BacktestResult


SIGNAL_SHARPE = 1.25
SIGNAL_FITNESS = 0.8
MIN_DISTINCT_FIELDS = 3
MIN_SAMPLES = 4
MIN_FAILURE_RATE = 0.80
MAX_AVERAGE_SHARPE = 0.10


@dataclass(frozen=True)
class CompletedExpression:
    expression: str
    fields: tuple[str, ...]
    sharpe: float
    fitness: float
    checks_passed: bool
    alpha_sha: str = ""
    family: str = "base"


@dataclass(frozen=True)
class ResultPruneRule:
    pattern: str
    pattern_type: str
    reason: str


def is_signal_parent(result: BacktestResult | CompletedExpression) -> bool:
    """Return whether a result qualifies for one bounded optimization branch."""
    return result.sharpe > SIGNAL_SHARPE and result.fitness > SIGNAL_FITNESS


def derive_consensus_prune_rules(rows: Sequence[CompletedExpression]) -> list[ResultPruneRule]:
    """Derive safe structural rules from cross-field, consistently failed results."""
    by_template: dict[str, list[CompletedExpression]] = {}
    for row in rows:
        template = abstract_template(row.expression, row.fields)
        if template != row.expression:
            by_template.setdefault(template, []).append(row)

    rules: list[ResultPruneRule] = []
    for template, samples in sorted(by_template.items()):
        if len(samples) < MIN_SAMPLES or any(is_signal_parent(sample) for sample in samples):
            continue
        fields = {field for sample in samples for field in sample.fields}
        failures = [sample for sample in samples if not sample.checks_passed or sample.sharpe <= MAX_AVERAGE_SHARPE]
        average_sharpe = sum(sample.sharpe for sample in samples) / len(samples)
        if (
            len(fields) >= MIN_DISTINCT_FIELDS
            and len(failures) / len(samples) >= MIN_FAILURE_RATE
            and average_sharpe <= MAX_AVERAGE_SHARPE
        ):
            prefix = template.split("{", 1)[0]
            if prefix:
                rules.append(ResultPruneRule(prefix, "prefix", "consensus failure"))
    return rules
