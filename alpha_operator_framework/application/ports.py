"""Typed technical boundaries used by application use cases."""

from __future__ import annotations

from typing import Protocol

from alpha_operator_framework.experiment.models import ExperimentBatch


class ExperimentRepository(Protocol):
    def save_batch(self, batch: ExperimentBatch) -> None: ...

    def load_batch(self, batch_id: str) -> ExperimentBatch | None: ...
