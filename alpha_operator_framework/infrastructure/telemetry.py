"""In-memory operational metrics adapter for research batches."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from alpha_operator_framework.experiment.lifecycle import BatchTransition
from alpha_operator_framework.experiment.models import ExperimentBatch


class ResearchTelemetry:
    def __init__(self) -> None:
        self._transitions: Counter[str] = Counter()
        self._pruning_reasons: Counter[str] = Counter()
        self._backtests_completed = 0
        self._quota = {"planned": 0, "consumed": 0}
        self._retryable_batches = 0

    def record_transition(self, batch: ExperimentBatch, event: BatchTransition) -> None:
        if event.accepted:
            self._transitions[event.to_state.value] += 1
            if event.to_state.value in {"PARTIAL_FAILED", "FAILED"}:
                self._retryable_batches += 1

    def record_pruning_reason(self, reason: str) -> None:
        self._pruning_reasons[reason] += 1

    def record_quota(self, *, planned: int, consumed: int) -> None:
        self._quota["planned"] += planned
        self._quota["consumed"] += consumed

    def record_backtests_completed(self, count: int) -> None:
        self._backtests_completed += count

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {"batch_transitions": dict(self._transitions), "backtests_completed": self._backtests_completed,
                "pruning_reasons": dict(self._pruning_reasons), "quota": dict(self._quota),
                "retryable_batches": self._retryable_batches}

    def export_json(self) -> str:
        return json.dumps(self.snapshot(), sort_keys=True)


class JsonLinesTelemetrySink:
    """Append telemetry snapshots for external log collectors."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def publish(self, telemetry: ResearchTelemetry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(telemetry.export_json() + "\n")
