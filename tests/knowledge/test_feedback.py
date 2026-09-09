"""KnowledgeBase feedback tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate


def test_one_pruned_template_observation_does_not_blacklist_its_structure() -> None:
    batch = ExperimentBatch("batch", "key")
    batch.record_result(BacktestResult("task", "rank(close)", -0.6, 0.0, 0.9, 0.0, False))
    batch.record_evaluation(EvaluationRecord("task", "REJECTED", 3, True))
    candidate = Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "bad-template")

    snapshot = KnowledgeBase().apply_batch(batch, {"task": "bad-template"})

    assert not snapshot.rejects(candidate)
    assert snapshot.field_scores["close"] < 0
    assert snapshot.operator_scores["rank"] < 0


def test_consistently_hard_failing_template_is_rejected_after_minimum_support() -> None:
    batch = ExperimentBatch("batch", "key")
    templates = {}
    for index in range(3):
        task_id = f"task-{index}"
        batch.record_result(BacktestResult(task_id, f"rank(close_{index})", -0.6, 0.0, 0.2, 0.0, False))
        batch.record_evaluation(EvaluationRecord(task_id, "PRUNED", 2, True))
        templates[task_id] = "bad-template"

    snapshot = KnowledgeBase().apply_batch(batch, templates)

    assert snapshot.rejects(Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "bad-template"))


def test_correlation_only_pruning_does_not_count_as_template_hard_failure() -> None:
    batch = ExperimentBatch("batch", "key")
    templates = {}
    for index in range(3):
        task_id = f"task-{index}"
        batch.record_result(BacktestResult(task_id, f"rank(close_{index})", 1.2, 1.0, 0.2, 5.0, True))
        batch.record_evaluation(EvaluationRecord(task_id, "READY", 1, True))
        templates[task_id] = "otherwise-good-template"

    snapshot = KnowledgeBase().apply_batch(batch, templates)

    assert not snapshot.rejects(Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "otherwise-good-template"))
