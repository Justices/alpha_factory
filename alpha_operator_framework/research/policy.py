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
    templates: tuple[Any, ...] = ()
    prohibited_patterns: tuple[str, ...] = ()
    evaluation: Mapping[str, float] = None  # type: ignore[assignment]
    settings: Mapping[str, Any] = None  # type: ignore[assignment]
    template_promotion: Mapping[str, Any] = None  # type: ignore[assignment]

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
        settings = dict(data.get("settings", {}))
        promotion = dict(data.get("template_promotion", {}))
        if any(key not in {"field", "operator", "template", "novelty", "uncertainty"} or float(value) < 0 for key, value in weights.items()):
            raise ValueError("weights are invalid")
        if any(key not in {"min_sharpe", "min_fitness", "min_margin", "max_turnover"} for key in evaluation):
            raise ValueError("evaluation is invalid")
        if float(evaluation.get("max_turnover", 0.70)) <= 0 or float(evaluation.get("max_turnover", 0.70)) > 1:
            raise ValueError("evaluation.max_turnover is invalid")
        if set(settings) - {"delay", "decay", "neutralization", "truncation"}:
            raise ValueError("settings are invalid")
        if int(settings.get("delay", 1)) < 0 or int(settings.get("decay", 8)) < 0:
            raise ValueError("settings are invalid")
        if not 0 < float(settings.get("truncation", 0.08)) <= 1:
            raise ValueError("settings are invalid")
        if set(promotion) - {"min_support", "min_sharpe", "min_fitness", "max_correlation", "structural_max_correlation", "platform_max_correlation", "observation_window"}:
            raise ValueError("template_promotion is invalid")
        if int(promotion.get("min_support", 1)) < 1 or int(promotion.get("observation_window", 1)) < 1:
            raise ValueError("template_promotion is invalid")
        templates = tuple(data.get("templates", ()))
        if any(not item for item in templates):
            raise ValueError("templates are invalid")
        patterns = tuple(str(item) for item in pruning.get("prohibited_patterns", ()))
        return cls(str(data.get("version", "default")), region, universe, budget, strategy, weights, templates, patterns, evaluation, settings, promotion)

    def construction_templates(self):
        from .construction import ConstructionTemplate

        templates = []
        for item in self.templates:
            if not isinstance(item, Mapping):
                raise ValueError("policy templates must be mappings with id, expression, family, and operators")
            required = {"id", "expression", "family", "operators"}
            if not required <= item.keys() or "{field}" not in str(item["expression"]):
                raise ValueError("policy template is invalid")
            templates.append(ConstructionTemplate(
                str(item["id"]), str(item["expression"]), str(item["family"]), tuple(str(value) for value in item["operators"]),
            ))
        return tuple(templates)

    def to_research_policy(self) -> ResearchPolicy:
        weights = self.weights or {}
        evaluation = self.evaluation or {}
        settings = self.settings or {}
        promotion = self.template_promotion or {}
        return ResearchPolicy(self.region, self.universe, self.max_backtests,
            field_weight=float(weights.get("field", 1.0)), operator_weight=float(weights.get("operator", 1.0)),
            template_weight=float(weights.get("template", 1.0)), novelty_weight=float(weights.get("novelty", 1.0)),
            uncertainty_weight=float(weights.get("uncertainty", 1.0)), prohibited_patterns=self.prohibited_patterns,
            policy_version=self.version, selection_strategy=self.selection_strategy,
            min_sharpe=float(evaluation.get("min_sharpe", 1.0)), min_fitness=float(evaluation.get("min_fitness", 0.8)),
            min_margin=float(evaluation.get("min_margin", 4.0)), max_turnover=float(evaluation.get("max_turnover", 0.70)),
            delay=int(settings.get("delay", 1)), decay=int(settings.get("decay", 8)),
            neutralization=str(settings.get("neutralization", "SUBINDUSTRY")), truncation=float(settings.get("truncation", 0.08)),
            template_min_support=int(promotion.get("min_support", 1)), template_min_sharpe=float(promotion.get("min_sharpe", 1.0)),
            template_min_fitness=float(promotion.get("min_fitness", 0.8)), template_max_correlation=float(promotion.get("max_correlation", 0.70)),
            template_structural_max_correlation=float(promotion.get("structural_max_correlation", promotion.get("max_correlation", 0.70))),
            template_platform_max_correlation=float(promotion.get("platform_max_correlation", promotion.get("max_correlation", 0.70))),
            template_observation_window=int(promotion.get("observation_window", 1)))


def build_selector(policy: ResearchPolicy):
    selectors = {
        "weighted_stratified": WeightedStratifiedSelector,
        "stratified": WeightedStratifiedSelector,
        "thompson": ThompsonSelector,
        "ucb": UcbSelector,
        "diversity": DiversitySelector,
        "d_optimal": DiversitySelector,
    }
    try:
        return selectors[policy.selection_strategy]()
    except KeyError as error:
        raise ValueError(f"Unknown selection strategy: {policy.selection_strategy}") from error


def validate_cli_policy_overrides(policy: ResearchPolicy, overrides: Mapping[str, Any]) -> None:
    """Reject ambiguous policy-file/CLI combinations instead of silently ignoring a value."""
    aliases = {"algorithm": "selection_strategy"}
    for name, value in overrides.items():
        if value is None:
            continue
        attribute = aliases.get(name, name)
        if getattr(policy, attribute) != value:
            raise ValueError(f"CLI override conflicts with policy file: {name}")


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
