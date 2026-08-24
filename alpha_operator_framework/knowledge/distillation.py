"""Pure template distillation from evaluated experiment facts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from alpha_operator_framework.domain.ast import extract_ast_fields
from alpha_operator_framework.experiment.models import ExperimentBatch


@dataclass(frozen=True)
class DistilledTemplate:
    expression_template: str
    support: int
    source_task_ids: tuple[str, ...]


def _abstract(expression: str) -> str:
    template = expression
    for index, field_id in enumerate(sorted(extract_ast_fields(expression), key=len, reverse=True)):
        slot = chr(ord("a") + index)
        template = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(field_id)}(?![A-Za-z0-9_])",
            "{" + slot + "}",
            template,
        )
    return template


def distill_templates(
    batch: ExperimentBatch, *, min_support: int = 1, min_sharpe: float = float("-inf"), min_fitness: float = float("-inf"),
) -> list[DistilledTemplate]:
    """Abstract qualified results into deterministic reusable template evidence."""
    sources: dict[str, list[str]] = {}
    for task_id, result in batch.results.items():
        evaluation = batch.evaluations.get(task_id)
        if evaluation is None or evaluation.verdict != "READY" or evaluation.pruned:
            continue
        if result.sharpe < min_sharpe or result.fitness < min_fitness:
            continue
        template = _abstract(result.expression)
        sources.setdefault(template, []).append(task_id)
    return [
        DistilledTemplate(template, len(task_ids), tuple(task_ids))
        for template, task_ids in sources.items()
        if len(task_ids) >= min_support
    ]
