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
        region, universe = str(data.get("region", "")), str(data.get("universe", ""))
        budget = int(data.get("max_backtests", 0))
        strategy = str(data.get("selection_strategy", "weighted_stratified"))
        if not region or not universe:
            raise ValueError("region and universe are required")
        if budget <= 0:
            raise ValueError("max_backtests must be positive")
        if strategy not in {"weighted_stratified", "thompson", "ucb", "diversity"}:
            raise ValueError("selection_strategy is invalid")
        return cls(str(data.get("version", "default")), region, universe, budget, strategy)

    def to_research_policy(self) -> ResearchPolicy:
        return ResearchPolicy(self.region, self.universe, self.max_backtests, policy_version=self.version, selection_strategy=self.selection_strategy)


def build_selector(policy: ResearchPolicy):
    selectors = {"weighted_stratified": WeightedStratifiedSelector, "thompson": ThompsonSelector, "ucb": UcbSelector, "diversity": DiversitySelector}
    try:
        return selectors[policy.selection_strategy]()
    except KeyError as error:
        raise ValueError(f"Unknown selection strategy: {policy.selection_strategy}") from error


def load_policy(path: Path) -> PolicySnapshot:
    """Load a versioned JSON or YAML policy snapshot without ambient configuration."""
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
            loader = getattr(yaml, "safe_load", None)
        except ImportError:
            loader = None
        if loader is not None:
            data = loader(content)
        else:
            data = {
                key.strip(): int(value.strip()) if value.strip().isdigit() else value.strip()
                for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")
                for key, value in [line.split(":", 1)]
            }
    else:
        data = json.loads(content)
    if not isinstance(data, Mapping):
        raise ValueError("Policy file must contain a mapping")
    return PolicySnapshot.from_mapping(data)
