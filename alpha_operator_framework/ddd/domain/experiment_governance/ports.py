"""Experiment Governance Bounded Context - Ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .models import BacktestTask, ExperimentBatch, NormalizedBacktestResult


class BacktestGatewayPort(ABC):
    """Port for submitting batches to the simulation execution backend."""

    @abstractmethod
    def submit_and_poll_batch(
        self,
        tasks: List[BacktestTask],
        settings: Dict[str, Any],
        idempotency_key: str,
    ) -> List[NormalizedBacktestResult]:
        ...


class ExperimentRepositoryPort(ABC):
    """Port for persisting and retrieving ExperimentBatch aggregates."""

    @abstractmethod
    def save_batch(self, batch: ExperimentBatch) -> None:
        ...

    @abstractmethod
    def load_batch(self, batch_id: str) -> Optional[ExperimentBatch]:
        ...
