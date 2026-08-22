"""Field Research Bounded Context - Ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional
from .models import FieldProfile, FieldSnapshot, FieldUniverse


class FieldCatalogPort(ABC):
    """Port for querying raw data fields from external catalog/data API."""

    @abstractmethod
    def fetch_field_snapshots(self, region: str, universe: str, dataset_ids: Optional[List[str]] = None) -> List[FieldSnapshot]:
        ...


class FieldProfileRepositoryPort(ABC):
    """Port for persisting and retrieving FieldUniverse aggregates."""

    @abstractmethod
    def load_universe(self, region: str, universe: str) -> Optional[FieldUniverse]:
        ...

    @abstractmethod
    def save_universe(self, universe: FieldUniverse) -> None:
        ...
