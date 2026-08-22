"""Base Selection Policy Interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Sequence
from ..models import Candidate, ResearchPolicy, SelectionDecision
from ...ports import RandomSource


class SelectionPolicy(ABC):
    """Abstract pure policy for proposing backtest candidates from a pre-pruned pool."""

    @abstractmethod
    def select(
        self,
        candidates: Sequence[Candidate],
        policy: ResearchPolicy,
        random_source: RandomSource,
        context_knowledge: Any = None,
    ) -> List[SelectionDecision]:
        """Propose selection decisions deterministically."""
        ...
