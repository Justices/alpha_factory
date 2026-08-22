"""ExperimentBatch lifecycle tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import ExperimentBatch
from alpha_operator_framework.research.round import Candidate, ResearchPolicy


def test_backtest_task_keeps_candidate_lineage_and_idempotency_key() -> None:
    candidate = Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")
    policy = ResearchPolicy(region="GBR", universe="TOP700", max_backtests=1)
    batch = ExperimentBatch(batch_id="batch-1", idempotency_key="batch-key")

    task = batch.create_tasks([candidate], policy)[0]

    assert task.candidate_id == candidate.candidate_id
    assert task.expression == candidate.expression
    assert task.idempotency_key == "batch-key:0"
