"""Candidate Exploration Bounded Context - Ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from .models import SelectionRound


class CandidateRepositoryPort(ABC):
    """Port for persisting and loading SelectionRound aggregates."""

    @abstractmethod
    def save_round(self, selection_round: SelectionRound) -> None:
        ...

    @abstractmethod
    def load_round(self, round_id: str) -> Optional[SelectionRound]:
        ...
