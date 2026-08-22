"""Versioned, serializable research-policy configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .round import ResearchPolicy
from .selection import DiversitySelector, ThompsonSelector, UcbSelector, WeightedStratifiedSelector


@dataclass(frozen=True)
class PolicySnapshot:
    version: str
    region: str
    universe: str
    max_backtests: int
    selection_strategy: str = "weighted_stratified"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PolicySnapshot":
        return cls(str(data.get("version", "default")), str(data["region"]), str(data["universe"]), int(data["max_backtests"]), str(data.get("selection_strategy", "weighted_stratified")))

    def to_research_policy(self) -> ResearchPolicy:
        return ResearchPolicy(self.region, self.universe, self.max_backtests, policy_version=self.version, selection_strategy=self.selection_strategy)


def build_selector(policy: ResearchPolicy):
    selectors = {"weighted_stratified": WeightedStratifiedSelector, "thompson": ThompsonSelector, "ucb": UcbSelector, "diversity": DiversitySelector}
    try:
        return selectors[policy.selection_strategy]()
    except KeyError as error:
        raise ValueError(f"Unknown selection strategy: {policy.selection_strategy}") from error


def load_policy(path: Path) -> PolicySnapshot:
    """Load a versioned JSON policy snapshot without ambient configuration."""
    return PolicySnapshot.from_mapping(json.loads(path.read_text(encoding="utf-8")))
