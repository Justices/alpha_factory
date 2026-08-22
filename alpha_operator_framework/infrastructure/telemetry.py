"""In-memory operational metrics adapter for research batches."""

from __future__ import annotations

from collections import Counter

from alpha_operator_framework.experiment.lifecycle import BatchTransition
from alpha_operator_framework.experiment.models import ExperimentBatch


class ResearchTelemetry:
    def __init__(self) -> None:
        self._transitions: Counter[str] = Counter()
        self._backtests_completed = 0

    def record_transition(self, batch: ExperimentBatch, event: BatchTransition) -> None:
        if event.accepted:
            self._transitions[event.to_state.value] += 1

    def record_backtests_completed(self, count: int) -> None:
        self._backtests_completed += count

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {"batch_transitions": dict(self._transitions), "backtests_completed": self._backtests_completed}
