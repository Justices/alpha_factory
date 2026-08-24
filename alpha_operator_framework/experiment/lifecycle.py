"""Explicit, replayable lifecycle transitions for experiment batches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ExperimentBatch


class BatchState(StrEnum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"
    EVALUATED = "EVALUATED"


@dataclass(frozen=True)
class BatchTransition:
    batch_id: str
    from_state: BatchState
    to_state: BatchState
    accepted: bool
    reason: str


_ALLOWED: dict[BatchState, frozenset[BatchState]] = {
    BatchState.PLANNED: frozenset({BatchState.SUBMITTED}),
    BatchState.SUBMITTED: frozenset({BatchState.RUNNING, BatchState.FAILED}),
    BatchState.RUNNING: frozenset({BatchState.COMPLETED, BatchState.PARTIAL_FAILED, BatchState.FAILED}),
    BatchState.COMPLETED: frozenset({BatchState.EVALUATED}),
    BatchState.PARTIAL_FAILED: frozenset({BatchState.RUNNING, BatchState.EVALUATED}),
    BatchState.FAILED: frozenset(),
    BatchState.EVALUATED: frozenset(),
}


def transition(batch: ExperimentBatch, target: BatchState) -> BatchTransition:
    """Apply a legal transition and retain its immutable audit fact."""
    source = batch.state
    accepted = target in _ALLOWED[source]
    record = BatchTransition(
        batch_id=batch.batch_id,
        from_state=source,
        to_state=target,
        accepted=accepted,
        reason="ACCEPTED" if accepted else "INVALID_TRANSITION",
    )
    if accepted:
        batch.state = target
        batch.transitions.append(record)
    return record
