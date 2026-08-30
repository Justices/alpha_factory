"""Pure cross-round knowledge aggregate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from alpha_operator_framework.experiment.models import ExperimentBatch
from alpha_operator_framework.domain.ast import validate_expression
from alpha_operator_framework.research.round import KnowledgeSnapshot


_NON_FIELDS = {"rank", "ts_rank", "group_rank", "subindustry", "industry", "sector"}


@dataclass
class KnowledgeBase:
    version: int = 0
    field_scores: dict[str, float] = field(default_factory=dict)
    operator_scores: dict[str, float] = field(default_factory=dict)
    template_scores: dict[str, float] = field(default_factory=dict)
    rejected_templates: set[str] = field(default_factory=set)
    field_trials: dict[str, int] = field(default_factory=dict)

    def apply_batch(self, batch: ExperimentBatch, task_templates: Mapping[str, str]) -> KnowledgeSnapshot:
        for task_id, result in batch.results.items():
            fields = {
                token
                for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", result.expression)
                if token not in _NON_FIELDS
            }
            reward = 0.2 if result.sharpe >= 1.0 else -0.2 if result.sharpe <= 0.0 else 0.0
            for field_id in fields:
                self.field_scores[field_id] = self.field_scores.get(field_id, 0.0) + reward
                self.field_trials[field_id] = self.field_trials.get(field_id, 0) + 1
            for operator in validate_expression(result.expression).operators_used:
                self.operator_scores[operator] = self.operator_scores.get(operator, 0.0) + reward
            evaluation = batch.evaluations.get(task_id)
            template_id = task_templates.get(task_id)
            if template_id:
                self.template_scores[template_id] = self.template_scores.get(template_id, 0.0) + reward
                if evaluation and evaluation.pruned:
                    self.rejected_templates.add(template_id)
        self.version += 1
        return self.snapshot()

    def snapshot(self) -> KnowledgeSnapshot:
        return KnowledgeSnapshot(
            version=self.version,
            field_scores=dict(self.field_scores),
            operator_scores=dict(self.operator_scores),
            template_scores=dict(self.template_scores),
            rejected_templates=tuple(sorted(self.rejected_templates)),
            field_trials=dict(self.field_trials),
        )

    def distill_batch(self, batch: ExperimentBatch):
        """Expose qualified template evidence without coupling callers to its algorithm."""
        from .distillation import distill_templates

        return distill_templates(batch)
