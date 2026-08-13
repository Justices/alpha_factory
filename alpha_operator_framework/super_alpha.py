"""Pure Super Alpha candidate construction and BRAIN request encoding."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from itertools import product
from typing import Any, Iterable


@dataclass(frozen=True)
class SuperAlphaConfig:
    min_sharpe: float = 1.0
    min_fitness: float = 0.8
    max_turnover: float = 0.50
    max_self_correlation: float = 0.70
    max_prod_correlation: float = 0.70
    max_candidates: int = 6


SELECTION_TEMPLATES = (
    ("baseline", "1"),
    ("quality_turnover", "if_else(sharpe >= 1.5 && fitness >= 0.8 && turnover >= 0.10 && turnover <= 0.35, sharpe * fitness, nan)"),
    ("correlation_gate", "if_else(self_correlation <= 0.55 && prod_correlation <= 0.55 && turnover >= 0.10 && turnover <= 0.35, fitness, nan)"),
)

COMBO_TEMPLATES = (
    ("equal_weight", "1"),
    ("combo_a_252", 'combo_a(alpha, nlength=252, mode="algo1")'),
    ("internal_corr_252", "stats = generate_stats(alpha); inner = self_corr(stats.returns, 252); clean = if_else(inner == 1.0, nan, inner); 1 - reduce_max(clean)"),
)


def _number(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) if row.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def eligible_components(rows: Iterable[dict[str, Any]], config: SuperAlphaConfig) -> list[dict[str, Any]]:
    """Return source regular alphas that pass explicit performance and risk gates."""
    result = []
    for row in rows:
        if not row.get("alpha_id") or not row.get("expression"):
            continue
        if (_number(row, "sharpe") < config.min_sharpe or _number(row, "fitness") < config.min_fitness
                or _number(row, "turnover") > config.max_turnover
                or _number(row, "sc_value") > config.max_self_correlation
                or _number(row, "pc_value") > config.max_prod_correlation):
            continue
        result.append(dict(row))
    return sorted(result, key=lambda item: (-_number(item, "fitness"), -_number(item, "sharpe"), str(item["alpha_id"])))


def build_super_candidates(rows: Iterable[dict[str, Any]], config: SuperAlphaConfig,
                           settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a deterministic, bounded cross-product of structurally distinct templates."""
    components = eligible_components(rows, config)
    component_ids = [str(row["alpha_id"]) for row in components]
    candidates = []
    for (selection_name, selection), (combo_name, combo) in product(SELECTION_TEMPLATES, COMBO_TEMPLATES):
        identity = {"components": component_ids, "selection": selection, "combo": combo, "settings": settings}
        candidate_sha = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        candidates.append({"candidate_sha": candidate_sha, "component_ids": component_ids,
                           "selection_name": selection_name, "selection": selection,
                           "combo_name": combo_name, "combo": combo})
        if len(candidates) >= config.max_candidates:
            break
    return candidates


def super_simulation_payload(candidate: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Encode one candidate as a BRAIN SUPER simulation request without secrets."""
    platform_settings = {key: value for key, value in settings.items() if key != "simulation_type"}
    return {"type": "SUPER", "settings": platform_settings,
            "selection": candidate["selection"], "combo": candidate["combo"]}


__all__ = ["SuperAlphaConfig", "eligible_components", "build_super_candidates", "super_simulation_payload"]
