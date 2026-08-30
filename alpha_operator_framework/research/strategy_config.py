"""Explicit configuration for composable Alpha construction strategies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_STRATEGY_KINDS = frozenset({
    "database_template",
    "raw_first_order",
    "depth_construction",
    "field_composition",
    "group_second_order",
    "signal_validation",
    "literature_llm",
    "ai_naked_signal",
})
SUPPORTED_PARENT_SOURCES = frozenset({
    "raw_fields",
    "qualified_candidates",
    "raw_and_qualified_candidates",
})
MAX_LEAF_FAMILY_QUOTA = 8
PLATFORM_BATCH_SIZE = 8


@dataclass(frozen=True)
class StructuralConstraint:
    """An exact value or an inclusive integer range."""

    exact: int | None = None
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if self.exact is not None and (self.minimum is not None or self.maximum is not None):
            raise ValueError("structural constraint cannot combine exact with min/max")
        values = [value for value in (self.exact, self.minimum, self.maximum) if value is not None]
        if not values:
            raise ValueError("structural constraint requires exact or min/max")
        if any(isinstance(value, bool) or int(value) != value or value < 0 for value in values):
            raise ValueError("structural constraint values must be non-negative integers")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("structural constraint min cannot exceed max")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, name: str) -> "StructuralConstraint":
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} must be a mapping")
        unknown = set(value) - {"exact", "min", "max"}
        if unknown:
            raise ValueError(f"{name} has unsupported keys: {', '.join(sorted(unknown))}")
        return cls(
            exact=_optional_int(value.get("exact"), f"{name}.exact"),
            minimum=_optional_int(value.get("min"), f"{name}.min"),
            maximum=_optional_int(value.get("max"), f"{name}.max"),
        )

    def contains(self, value: int) -> bool:
        if self.exact is not None:
            return value == self.exact
        return (self.minimum is None or value >= self.minimum) and (
            self.maximum is None or value <= self.maximum
        )

    def to_mapping(self) -> dict[str, int]:
        if self.exact is not None:
            return {"exact": self.exact}
        result: dict[str, int] = {}
        if self.minimum is not None:
            result["min"] = self.minimum
        if self.maximum is not None:
            result["max"] = self.maximum
        return result


@dataclass(frozen=True)
class Threshold:
    operator: str
    value: float

    def __post_init__(self) -> None:
        if self.operator not in {"gt", "gte"}:
            raise ValueError("parent gate operator must be gt or gte")

    def passes(self, actual: float) -> bool:
        return actual > self.value if self.operator == "gt" else actual >= self.value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, name: str) -> "Threshold":
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} must be a mapping")
        try:
            threshold = float(value["value"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{name}.value must be numeric") from error
        return cls(operator=str(value.get("operator", "gt")), value=threshold)

    def to_mapping(self) -> dict[str, object]:
        return {"operator": self.operator, "value": self.value}


@dataclass(frozen=True)
class ParentGate:
    sharpe: Threshold = Threshold("gt", 1.25)
    fitness: Threshold = Threshold("gt", 0.8)

    def passes(self, sharpe: float, fitness: float) -> bool:
        return self.sharpe.passes(sharpe) and self.fitness.passes(fitness)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ParentGate":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("construction.parent_gate must be a mapping")
        unknown = set(value) - {"sharpe", "fitness"}
        if unknown:
            raise ValueError(f"construction.parent_gate has unsupported keys: {', '.join(sorted(unknown))}")
        return cls(
            sharpe=Threshold.from_mapping(value.get("sharpe", {"operator": "gt", "value": 1.25}), name="parent_gate.sharpe"),
            fitness=Threshold.from_mapping(value.get("fitness", {"operator": "gt", "value": 0.8}), name="parent_gate.fitness"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {"sharpe": self.sharpe.to_mapping(), "fitness": self.fitness.to_mapping()}


@dataclass(frozen=True)
class PromotionQualityGate:
    """Deterministic invalid-result checks applied before stage promotion."""

    min_long_short_sum: int = 0
    max_consecutive_flat_days: int = 200
    max_tail_flat_ratio: float = 0.30

    def __post_init__(self) -> None:
        if self.min_long_short_sum < 0:
            raise ValueError("promotion.quality.min_long_short_sum must be non-negative")
        if self.max_consecutive_flat_days < 1:
            raise ValueError("promotion.quality.max_consecutive_flat_days must be positive")
        if not 0.0 <= self.max_tail_flat_ratio <= 1.0:
            raise ValueError("promotion.quality.max_tail_flat_ratio must be between 0 and 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PromotionQualityGate":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("construction.promotion.quality must be a mapping")
        unknown = set(value) - {
            "min_long_short_sum", "max_consecutive_flat_days", "max_tail_flat_ratio",
        }
        if unknown:
            raise ValueError(f"promotion.quality has unsupported keys: {', '.join(sorted(unknown))}")
        return cls(
            min_long_short_sum=_required_int(
                value.get("min_long_short_sum", 0), "promotion.quality.min_long_short_sum",
            ),
            max_consecutive_flat_days=_required_int(
                value.get("max_consecutive_flat_days", 200),
                "promotion.quality.max_consecutive_flat_days",
            ),
            max_tail_flat_ratio=_bounded_float(
                value.get("max_tail_flat_ratio", 0.30),
                "promotion.quality.max_tail_flat_ratio", 0.0, 1.0,
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "min_long_short_sum": self.min_long_short_sum,
            "max_consecutive_flat_days": self.max_consecutive_flat_days,
            "max_tail_flat_ratio": self.max_tail_flat_ratio,
        }


@dataclass(frozen=True)
class CorrelationPromotionPolicy:
    """Post-backtest multi-channel PnL-correlation selection policy."""

    enabled: bool = False
    channels: tuple[str, ...] = ("sharpe", "fitness", "margin")
    first_band_size: int = 5
    second_band_size: int = 5
    first_threshold: float = 0.85
    second_threshold: float = 0.80
    final_threshold: float = 0.75
    min_periods: int = 100

    def __post_init__(self) -> None:
        allowed = {"sharpe", "fitness", "margin"}
        if not self.channels or any(channel not in allowed for channel in self.channels):
            raise ValueError("promotion.correlation.channels supports sharpe/fitness/margin")
        if self.first_band_size < 1 or self.second_band_size < 0:
            raise ValueError("promotion.correlation band sizes are invalid")
        if self.min_periods < 2:
            raise ValueError("promotion.correlation.min_periods must be at least 2")
        for value in (self.first_threshold, self.second_threshold, self.final_threshold):
            if not 0.0 <= value <= 1.0:
                raise ValueError("promotion.correlation thresholds must be between 0 and 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "CorrelationPromotionPolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("construction.promotion.correlation must be a mapping")
        unknown = set(value) - {
            "enabled", "channels", "first_band_size", "second_band_size",
            "first_threshold", "second_threshold", "final_threshold", "min_periods",
        }
        if unknown:
            raise ValueError(f"promotion.correlation has unsupported keys: {', '.join(sorted(unknown))}")
        raw_channels = value.get("channels", ["sharpe", "fitness", "margin"])
        if not isinstance(raw_channels, list):
            raise ValueError("promotion.correlation.channels must be a list")
        channels = tuple(dict.fromkeys(str(item).strip() for item in raw_channels if str(item).strip()))
        return cls(
            enabled=_required_bool(value.get("enabled", False), "promotion.correlation.enabled"),
            channels=channels,
            first_band_size=_required_int(
                value.get("first_band_size", 5), "promotion.correlation.first_band_size",
            ),
            second_band_size=_required_int(
                value.get("second_band_size", 5), "promotion.correlation.second_band_size",
            ),
            first_threshold=_bounded_float(
                value.get("first_threshold", 0.85), "promotion.correlation.first_threshold", 0.0, 1.0,
            ),
            second_threshold=_bounded_float(
                value.get("second_threshold", 0.80), "promotion.correlation.second_threshold", 0.0, 1.0,
            ),
            final_threshold=_bounded_float(
                value.get("final_threshold", 0.75), "promotion.correlation.final_threshold", 0.0, 1.0,
            ),
            min_periods=_required_int(
                value.get("min_periods", 100), "promotion.correlation.min_periods",
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "channels": list(self.channels),
            "first_band_size": self.first_band_size,
            "second_band_size": self.second_band_size,
            "first_threshold": self.first_threshold,
            "second_threshold": self.second_threshold,
            "final_threshold": self.final_threshold,
            "min_periods": self.min_periods,
        }


@dataclass(frozen=True)
class SignalValidationPolicy:
    enabled: bool = True
    minimum_sharpe_ratio: float = 0.50

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "SignalValidationPolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("construction.promotion.validation must be a mapping")
        unknown = set(value) - {"enabled", "minimum_sharpe_ratio"}
        if unknown:
            raise ValueError(f"promotion.validation has unsupported keys: {', '.join(sorted(unknown))}")
        return cls(
            enabled=_required_bool(value.get("enabled", True), "promotion.validation.enabled"),
            minimum_sharpe_ratio=_bounded_float(
                value.get("minimum_sharpe_ratio", 0.50),
                "promotion.validation.minimum_sharpe_ratio", 0.0, 1.0,
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "minimum_sharpe_ratio": self.minimum_sharpe_ratio,
        }


@dataclass(frozen=True)
class PromotionPolicy:
    quality: PromotionQualityGate = PromotionQualityGate()
    correlation: CorrelationPromotionPolicy = CorrelationPromotionPolicy()
    validation: SignalValidationPolicy = SignalValidationPolicy()
    early_stop_signal_count: int = 0

    def __post_init__(self) -> None:
        if self.early_stop_signal_count < 0:
            raise ValueError("promotion.early_stop_signal_count must be non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PromotionPolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("construction.promotion must be a mapping")
        unknown = set(value) - {"quality", "correlation", "validation", "early_stop_signal_count"}
        if unknown:
            raise ValueError(f"promotion has unsupported keys: {', '.join(sorted(unknown))}")
        return cls(
            quality=PromotionQualityGate.from_mapping(value.get("quality")),
            correlation=CorrelationPromotionPolicy.from_mapping(value.get("correlation")),
            validation=SignalValidationPolicy.from_mapping(value.get("validation")),
            early_stop_signal_count=_required_int(
                value.get("early_stop_signal_count", 0), "promotion.early_stop_signal_count",
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "quality": self.quality.to_mapping(),
            "correlation": self.correlation.to_mapping(),
            "validation": self.validation.to_mapping(),
            "early_stop_signal_count": self.early_stop_signal_count,
        }


@dataclass(frozen=True)
class ConstructionStrategyConfig:
    strategy_id: str
    kind: str
    families: tuple[str, ...]
    order_depth: StructuralConstraint
    field_count: StructuralConstraint
    quota_per_leaf_family: int = MAX_LEAF_FAMILY_QUOTA
    source: str = "raw_fields"
    stage: int = 1
    document: Path | None = None
    llm_profile: str | None = None

    @property
    def consumes_parents(self) -> bool:
        return self.source in {"qualified_candidates", "raw_and_qualified_candidates"}

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.strategy_id,
            "kind": self.kind,
            "families": list(self.families),
            "order_depth": self.order_depth.to_mapping(),
            "field_count": self.field_count.to_mapping(),
            "quota_per_leaf_family": self.quota_per_leaf_family,
            "source": self.source,
            "stage": self.stage,
        }
        if self.document is not None:
            result["document"] = str(self.document)
        if self.llm_profile is not None:
            result["llm_profile"] = self.llm_profile
        return result


@dataclass(frozen=True)
class ConstructionPlan:
    strategies: tuple[ConstructionStrategyConfig, ...]
    parent_gate: ParentGate = ParentGate()
    platform_batch_size: int = PLATFORM_BATCH_SIZE
    promotion: PromotionPolicy = PromotionPolicy()

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        base_path: Path | None = None,
    ) -> "ConstructionPlan":
        if not isinstance(value, Mapping):
            raise ValueError("research.construction must be a mapping")
        raw_strategies = value.get("strategies")
        if not isinstance(raw_strategies, list) or not raw_strategies:
            raise ValueError("research.construction.strategies must be a non-empty list")
        strategies: list[ConstructionStrategyConfig] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(raw_strategies):
            strategy = _parse_strategy(raw, index=index, base_path=base_path)
            if strategy.strategy_id in seen_ids:
                raise ValueError(f"duplicate construction strategy id: {strategy.strategy_id}")
            seen_ids.add(strategy.strategy_id)
            strategies.append(strategy)
        batch_size = _required_int(value.get("platform_batch_size", PLATFORM_BATCH_SIZE), "construction.platform_batch_size")
        if batch_size != PLATFORM_BATCH_SIZE:
            raise ValueError(f"construction.platform_batch_size must be {PLATFORM_BATCH_SIZE}")
        return cls(
            strategies=tuple(strategies),
            parent_gate=ParentGate.from_mapping(value.get("parent_gate")),
            platform_batch_size=batch_size,
            promotion=PromotionPolicy.from_mapping(value.get("promotion")),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "strategies": [strategy.to_mapping() for strategy in self.strategies],
            "parent_gate": self.parent_gate.to_mapping(),
            "platform_batch_size": self.platform_batch_size,
            "promotion": self.promotion.to_mapping(),
        }

    def strategies_for_stage(self, stage: int) -> tuple[ConstructionStrategyConfig, ...]:
        return tuple(item for item in self.strategies if item.stage == stage)

    def next_stage_for(self, strategy_id: str) -> int | None:
        current = next((item.stage for item in self.strategies if item.strategy_id == strategy_id), None)
        if current is None:
            return None
        later = sorted({item.stage for item in self.strategies if item.stage > current})
        return later[0] if later else None


def _parse_strategy(
    raw: object,
    *,
    index: int,
    base_path: Path | None,
) -> ConstructionStrategyConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"construction.strategies[{index}] must be a mapping")
    kind = str(raw.get("kind", "")).strip()
    if kind not in SUPPORTED_STRATEGY_KINDS:
        raise ValueError(f"unsupported construction strategy kind: {kind or '<missing>'}")
    strategy_id = str(raw.get("id") or f"{kind}-{index + 1}").strip()
    if not strategy_id:
        raise ValueError(f"construction.strategies[{index}].id cannot be empty")
    raw_families = raw.get("families")
    if not isinstance(raw_families, list) or not raw_families:
        raise ValueError(f"construction strategy {strategy_id} requires non-empty families")
    families = tuple(dict.fromkeys(str(item).strip() for item in raw_families if str(item).strip()))
    if not families:
        raise ValueError(f"construction strategy {strategy_id} requires non-empty families")
    source = str(raw.get("source") or _default_source(kind)).strip()
    if source not in SUPPORTED_PARENT_SOURCES:
        raise ValueError(f"unsupported construction source for {strategy_id}: {source}")
    if kind in {"database_template", "literature_llm", "ai_naked_signal", "raw_first_order"} and source != "raw_fields":
        raise ValueError(f"construction strategy {strategy_id} only supports source=raw_fields")
    quota = _required_int(raw.get("quota_per_leaf_family", MAX_LEAF_FAMILY_QUOTA), f"{strategy_id}.quota_per_leaf_family")
    if not 1 <= quota <= MAX_LEAF_FAMILY_QUOTA:
        raise ValueError(f"{strategy_id}.quota_per_leaf_family must be between 1 and {MAX_LEAF_FAMILY_QUOTA}")
    stage = _required_int(raw.get("stage", 1), f"{strategy_id}.stage")
    if stage < 1:
        raise ValueError(f"{strategy_id}.stage must be positive")
    document: Path | None = None
    llm_profile = str(raw.get("llm_profile") or "").strip() or None
    if kind == "literature_llm":
        raw_document = str(raw.get("document") or "").strip()
        if not raw_document:
            raise ValueError(f"literature strategy {strategy_id} requires document")
        document = Path(raw_document)
        if base_path is not None and not document.is_absolute():
            document = (base_path / document).resolve()
        if not document.exists() or not document.is_file():
            raise ValueError(f"literature document is unavailable: {document}")
        if llm_profile is None:
            raise ValueError(f"literature strategy {strategy_id} requires llm_profile")
    elif kind == "ai_naked_signal":
        if raw.get("document") is not None:
            raise ValueError(f"document is only valid for literature_llm: {strategy_id}")
        if llm_profile is None:
            raise ValueError(f"AI naked signal strategy {strategy_id} requires llm_profile")
    elif raw.get("document") is not None or raw.get("llm_profile") is not None:
        raise ValueError(f"document/llm_profile are only valid for literature_llm: {strategy_id}")
    return ConstructionStrategyConfig(
        strategy_id=strategy_id,
        kind=kind,
        families=families,
        order_depth=StructuralConstraint.from_mapping(raw.get("order_depth"), name=f"{strategy_id}.order_depth"),
        field_count=StructuralConstraint.from_mapping(raw.get("field_count"), name=f"{strategy_id}.field_count"),
        quota_per_leaf_family=quota,
        source=source,
        stage=stage,
        document=document,
        llm_profile=llm_profile,
    )


def _default_source(kind: str) -> str:
    if kind in {"depth_construction", "field_composition", "group_second_order", "signal_validation"}:
        return "raw_and_qualified_candidates"
    return "raw_fields"


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, name)


def _required_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        converted = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, str) and str(converted) != value.strip():
        raise ValueError(f"{name} must be an integer")
    return converted


def _required_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _bounded_float(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not minimum <= converted <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return converted


__all__ = [
    "ConstructionPlan",
    "ConstructionStrategyConfig",
    "MAX_LEAF_FAMILY_QUOTA",
    "PLATFORM_BATCH_SIZE",
    "ParentGate",
    "PromotionPolicy",
    "PromotionQualityGate",
    "CorrelationPromotionPolicy",
    "SignalValidationPolicy",
    "StructuralConstraint",
    "Threshold",
]
