"""Pure template distillation tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.distillation import distill_templates


def test_distillation_uses_only_ready_non_pruned_results() -> None:
    batch = ExperimentBatch("batch", "key")
    batch.record_result(BacktestResult("ready-a", "rank(returns)", 1.5, 1.1, 0.2, 5.0, True, "a"))
    batch.record_result(BacktestResult("ready-b", "rank(volume)", 1.4, 1.0, 0.2, 5.0, True, "b"))
    batch.record_result(BacktestResult("pruned", "rank(vwap)", -0.2, 0.0, 0.8, 0.0, False, "c"))
    batch.record_evaluation(EvaluationRecord("ready-a", "READY", 1, False))
    batch.record_evaluation(EvaluationRecord("ready-b", "READY", 1, False))
    batch.record_evaluation(EvaluationRecord("pruned", "PRUNED", 2, True))

    templates = distill_templates(batch)

    assert len(templates) == 1
    assert templates[0].expression_template == "rank({a})"
    assert templates[0].support == 2
    assert templates[0].source_task_ids == ("ready-a", "ready-b")


def test_distillation_does_not_promote_template_below_support_threshold() -> None:
    batch = ExperimentBatch("batch", "key")
    batch.record_result(BacktestResult("ready", "rank(returns)", 1.5, 1.1, 0.2, 5.0, True, "a"))
    batch.record_evaluation(EvaluationRecord("ready", "READY", 1, False))

    assert distill_templates(batch, min_support=2) == []


def test_distillation_enforces_quality_thresholds() -> None:
    batch = ExperimentBatch("batch", "key")
    batch.record_result(BacktestResult("weak", "rank(returns)", 1.1, 0.7, 0.2, 5.0, True, "a"))
    batch.record_evaluation(EvaluationRecord("weak", "READY", 1, False))

    assert distill_templates(batch, min_sharpe=1.2, min_fitness=0.8) == []
