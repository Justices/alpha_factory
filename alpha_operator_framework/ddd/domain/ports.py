"""Shared domain ports and interfaces."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any, List, Sequence, TypeVar

T = TypeVar("T")


class RandomSource(ABC):
    """Abstract port for random generation to allow 100% deterministic test replay."""

    @abstractmethod
    def random(self) -> float:
        """Return a random float in [0.0, 1.0)."""
        ...

    @abstractmethod
    def uniform(self, a: float, b: float) -> float:
        """Return a random float in [a, b]."""
        ...

    @abstractmethod
    def randint(self, a: int, b: int) -> int:
        """Return a random integer in [a, b]."""
        ...

    @abstractmethod
    def sample(self, population: Sequence[T], k: int) -> List[T]:
        """Sample k elements without replacement."""
        ...

    @abstractmethod
    def choices(self, population: Sequence[T], weights: Sequence[float], k: int) -> List[T]:
        """Sample k elements with replacement using weights."""
        ...

    @abstractmethod
    def shuffle(self, x: List[Any]) -> None:
        """Shuffle list in-place."""
        ...


class DeterministicRandomSource(RandomSource):
    """Deterministic implementation powered by seeded random.Random."""

    def __init__(self, seed: int = 42):
        self._seed = seed
        self._rng = random.Random(seed)

    @property
    def seed(self) -> int:
        return self._seed

    def random(self) -> float:
        return self._rng.random()

    def uniform(self, a: float, b: float) -> float:
        return self._rng.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def sample(self, population: Sequence[T], k: int) -> List[T]:
        if k > len(population):
            k = len(population)
        return self._rng.sample(list(population), k)

    def choices(self, population: Sequence[T], weights: Sequence[float], k: int) -> List[T]:
        return self._rng.choices(list(population), weights=list(weights), k=k)

    def shuffle(self, x: List[Any]) -> None:
        self._rng.shuffle(x)
