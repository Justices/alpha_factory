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
    weights: Mapping[str, float] = None  # type: ignore[assignment]
    templates: tuple[str, ...] = ()
    prohibited_patterns: tuple[str, ...] = ()
    evaluation: Mapping[str, float] = None  # type: ignore[assignment]

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
        weights = dict(data.get("weights", {}))
        evaluation = dict(data.get("evaluation", {}))
        pruning = dict(data.get("pruning", {}))
        if any(key not in {"field", "operator", "template", "novelty", "uncertainty"} or float(value) < 0 for key, value in weights.items()):
            raise ValueError("weights are invalid")
        if any(key not in {"min_sharpe", "min_fitness", "min_margin", "max_turnover"} for key in evaluation):
            raise ValueError("evaluation is invalid")
        if float(evaluation.get("max_turnover", 0.70)) <= 0 or float(evaluation.get("max_turnover", 0.70)) > 1:
            raise ValueError("evaluation.max_turnover is invalid")
        templates = tuple(str(item) for item in data.get("templates", ()))
        if any(not item for item in templates):
            raise ValueError("templates are invalid")
        patterns = tuple(str(item) for item in pruning.get("prohibited_patterns", ()))
        return cls(str(data.get("version", "default")), region, universe, budget, strategy, weights, templates, patterns, evaluation)

    def to_research_policy(self) -> ResearchPolicy:
        weights = self.weights or {}
        evaluation = self.evaluation or {}
        return ResearchPolicy(self.region, self.universe, self.max_backtests,
            field_weight=float(weights.get("field", 1.0)), operator_weight=float(weights.get("operator", 1.0)),
            template_weight=float(weights.get("template", 1.0)), novelty_weight=float(weights.get("novelty", 1.0)),
            uncertainty_weight=float(weights.get("uncertainty", 1.0)), prohibited_patterns=self.prohibited_patterns,
            policy_version=self.version, selection_strategy=self.selection_strategy,
            min_sharpe=float(evaluation.get("min_sharpe", 1.0)), min_fitness=float(evaluation.get("min_fitness", 0.8)),
            min_margin=float(evaluation.get("min_margin", 4.0)), max_turnover=float(evaluation.get("max_turnover", 0.70)))


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
