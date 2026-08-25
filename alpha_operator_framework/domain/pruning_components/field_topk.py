"""Field-aware result pruning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from alpha_operator_framework.domain.operators import ACCESS_LIMITED_OPS, basic_ops, extended_ops, group_ops, ts_ops, vec_ops
from .common import metric, number

_FIELD_RE = re.compile(r"ts_backfill\((?:[a-zA-Z0-9_]*\()?([a-zA-Z][a-zA-Z0-9_]*)(?:,|\))")
_NO_FIELD = ("__no_field__",)
_KNOWN_OPS = frozenset(set(basic_ops) | set(ts_ops) | set(group_ops) | set(vec_ops) | set(extended_ops) | set(ACCESS_LIMITED_OPS) | {"winsorize", "ts_backfill", "densify", "bucket", "s_log_1p", "ts_step", "std", "limit_volume", "rettype", "weight", "range", "if_else", "subindustry", "industry", "sector", "market", "country", "exchange"})


def extract_field_ids(expression: str) -> frozenset[str]:
    matched = frozenset(_FIELD_RE.findall(expression or ""))
    return matched if matched else frozenset(_NO_FIELD)


def extract_fields(expression: str) -> list[str]:
    matched = extract_field_ids(expression)
    if matched != frozenset(_NO_FIELD):
        return sorted(matched)
    return sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression or "")) - _KNOWN_OPS)


@dataclass(frozen=True)
class FieldTopKConfig:
    keep_per_field: int = 3
    by_metric: str = "sharpe"
    split_by_sign: bool = True


def field_topk_prune(results: Iterable[dict[str, Any]], config: FieldTopKConfig = FieldTopKConfig()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    buckets: dict[frozenset[str], list[dict[str, Any]]] = {}
    for row in results:
        fields = extract_field_ids(row.get("expression") or "")
        if config.split_by_sign:
            prefix = "-" if number(metric(row, config.by_metric)) < 0 else ""
            fields = frozenset(f"{prefix}{field}" for field in fields)
        buckets.setdefault(fields, []).append(row)
    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for fields, rows in buckets.items():
        label = ", ".join(sorted(fields)) if fields != frozenset(_NO_FIELD) else "<无字段>"
        for index, row in enumerate(sorted(rows, key=lambda item: abs(number(metric(item, config.by_metric))), reverse=True)):
            if config.keep_per_field > 0 and index < config.keep_per_field:
                kept.append(row)
            else:
                pruned.append({**row, "prune_reason": f"same_field_topk:{label}"})
    return kept, pruned
