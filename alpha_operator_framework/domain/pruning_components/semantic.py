"""Semantic field selection before simulation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence, Tuple

CATEGORY_RULES: Tuple[Tuple[str, frozenset[str]], ...] = (
    ("market", frozenset({"pv1", "pv2", "pv3", "model_raw", "price", "volume", "returns", "close", "cap", "trade", "quote", "bid", "ask", "open", "high", "low"})),
    ("analyst", frozenset({"analyst", "estimate", "target", "recommendation", "consensus", "broker", "revision", "rating", "eps_est", "surprise"})),
    ("fundamental", frozenset({"fundamental", "fund", "income", "balance", "cashflow", "assets", "equity", "earnings", "sales", "ebit", "eps", "bps", "dps", "roe", "roa", "margin", "revenue", "debt", "dividend", "book"})),
    ("model", frozenset({"mdl", "model", "ml", "predict", "score", "pca", "factor", "risk", "momentum", "value", "quality", "growth", "volatility", "skew"})),
    ("alternative", frozenset({"news", "sentiment", "social", "search", "option", "emo", "analyst_call", "web", "consumer", "supply", "satellite", "transaction"})),
    ("structural", frozenset({"industry", "sector", "group", "gics", "subindustry", "sta", "universe", "classification", "listing", "exchange", "index", "member"})),
)
FALLBACK_CATEGORY = "other"


def classify_field(field: Any) -> str:
    dataset = str(getattr(field, "dataset_id", "") or "").lower()
    description = str(getattr(field, "description", "") or "").lower()
    words = set(re.split(r"[\s_\-/]+", description))
    for category, keywords in CATEGORY_RULES:
        if any(keyword in dataset or keyword in description or keyword in words for keyword in keywords):
            return category
    return FALLBACK_CATEGORY


@dataclass(frozen=True)
class SemanticPruneConfig:
    keep_per_category: int = 3
    min_coverage: float = 0.0
    prefer_cold: bool = True
    category_rules: Tuple[Tuple[str, frozenset[str]], ...] = CATEGORY_RULES


def semantic_prune_fields(field_specs: Sequence[Any], config: SemanticPruneConfig = SemanticPruneConfig()) -> tuple[list[Any], list[dict[str, Any]]]:
    keep_n = max(config.keep_per_category, 0)
    buckets: dict[str, list[Any]] = {}
    for field in field_specs:
        if field.type not in ("MATRIX", "VECTOR") or (getattr(field, "coverage", 0) or 0) < config.min_coverage:
            continue
        buckets.setdefault(classify_field(field), []).append(field)
    kept: list[Any] = []
    pruned: list[dict[str, Any]] = []
    for category, fields in buckets.items():
        key = (lambda field: (field.user_count, -field.coverage, field.id)) if config.prefer_cold else (lambda field: (-field.coverage, field.user_count, field.id))
        for index, field in enumerate(sorted(fields, key=key)):
            if keep_n and index < keep_n:
                kept.append(field)
            else:
                pruned.append({"id": field.id, "category": category, "coverage": getattr(field, "coverage", 0), "user_count": getattr(field, "user_count", 0)})
    return kept, pruned
