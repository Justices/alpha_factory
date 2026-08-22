"""Post-result mutation tests."""

from __future__ import annotations

import random

from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.experiment.mutation import propose_mutations


def test_only_evaluated_non_pruned_results_are_mutation_parents() -> None:
    batch = ExperimentBatch(batch_id="batch", idempotency_key="key")
    batch.record_result(BacktestResult("ready", "rank(close)", 1.5, 1.1, 0.2, 5.0, True))
    batch.record_result(BacktestResult("pruned", "rank(open)", 1.5, 1.1, 0.2, 5.0, True))
    batch.record_evaluation(EvaluationRecord("ready", "READY", 1, False))
    batch.record_evaluation(EvaluationRecord("pruned", "READY", 1, True))

    proposals = propose_mutations(batch, max_proposals=2, random_source=random.Random(3))

    assert [proposal.parent_task_id for proposal in proposals] == ["ready"]
    assert proposals[0].expression != "rank(close)"
