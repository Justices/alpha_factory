"""Experiment batch lifecycle tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.models import ExperimentBatch


def test_batch_rejects_transition_that_skips_submission() -> None:
    batch = ExperimentBatch("batch", "key")

    decision = transition(batch, BatchState.COMPLETED)

    assert decision.accepted is False
    assert batch.state == BatchState.PLANNED


def test_batch_records_ordered_valid_transitions() -> None:
    batch = ExperimentBatch("batch", "key")

    transition(batch, BatchState.SUBMITTED)
    transition(batch, BatchState.RUNNING)
    decision = transition(batch, BatchState.COMPLETED)

    assert decision.accepted is True
    assert batch.state == BatchState.COMPLETED
    assert [entry.to_state for entry in batch.transitions] == [
        BatchState.SUBMITTED, BatchState.RUNNING, BatchState.COMPLETED,
    ]
