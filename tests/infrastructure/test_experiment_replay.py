"""SQLite replay tests for experiment batches."""

from __future__ import annotations

from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.infrastructure.sqlite import SqliteExperimentRepository
from alpha_operator_framework.research.round import Candidate, ResearchPolicy


def test_repository_replays_tasks_results_evaluations_and_transitions(tmp_path) -> None:
    batch = ExperimentBatch("batch", "key")
    task = batch.create_tasks(
        [Candidate("candidate", "rank(returns)", "family", ("returns",), ("rank",), "template")],
        ResearchPolicy("GBR", "TOP700", 1),
    )[0]
    transition(batch, BatchState.SUBMITTED)
    transition(batch, BatchState.RUNNING)
    batch.record_result(BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1"))
    batch.record_evaluation(EvaluationRecord(task.task_id, "READY", 1, False))
    transition(batch, BatchState.COMPLETED)
    repository = SqliteExperimentRepository(tmp_path / "rounds.db")

    repository.save_batch(batch)

    assert repository.load_batch("batch") == batch
