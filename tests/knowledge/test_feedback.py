"""KnowledgeBase feedback tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate


def test_pruned_template_is_unavailable_in_next_snapshot() -> None:
    batch = ExperimentBatch("batch", "key")
    batch.record_result(BacktestResult("task", "rank(close)", -0.6, 0.0, 0.9, 0.0, False))
    batch.record_evaluation(EvaluationRecord("task", "REJECTED", 3, True))
    candidate = Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "bad-template")

    snapshot = KnowledgeBase().apply_batch(batch, {"task": "bad-template"})

    assert snapshot.rejects(candidate)
    assert snapshot.field_scores["close"] < 0
    assert snapshot.operator_scores["rank"] < 0
