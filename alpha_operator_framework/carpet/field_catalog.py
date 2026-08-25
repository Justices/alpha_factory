"""Candidate field loading for carpet mining."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from alpha_operator_framework.carpet.models import CarpetMiningConfig
from alpha_operator_framework.domain.ast import extract_ast_fields
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.research.field_loader import load_real_market_fields

logger = logging.getLogger(__name__)


def _extract_task_fields(task: Task) -> List[str]:
    """Extract atomic feature fields used by a task."""
    if task.meta:
        if isinstance(task.meta.get("field"), str):
            return [task.meta["field"]]
        if isinstance(task.meta.get("fields"), (list, tuple)):
            return list(task.meta["fields"])
    if task.base_fields:
        return list(task.base_fields)
    try:
        fields = extract_ast_fields(task.expression)
        if fields:
            return list(fields)
    except Exception:
        pass
    excluded = {
        "rank", "group_rank", "group_neutralize", "group_zscore", "group_scale", "ts_scale", "ts_rank",
        "ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev", "subindustry", "industry",
        "sector", "market", "cap", "winsorize", "ts_backfill", "vec_avg", "vec_sum", "vec_min",
        "vec_max", "vec_stddev", "vec_range", "std",
    }
    return [token for token in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", task.expression) if token not in excluded and not token.isdigit()]


def load_available_fields(config: CarpetMiningConfig) -> List[Dict[str, Any]]:
    """Load usable fields for the configured market and datasets."""
    specs = load_real_market_fields(
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        datasets=config.datasets,
        max_fields=300,
    )
    excluded = {"close", "open", "high", "low", "vwap", "sharesout", "market_cap"}
    fields = [
        {"id": spec.id, "dataset_id": spec.dataset_id, "type": spec.type,
         "coverage": spec.coverage, "description": spec.description}
        for spec in specs if spec.id.lower() not in excluded
    ]
    logger.info("成功加载 %s 个候选字段 (来自数据集: %s)", len(fields), ", ".join(config.datasets))
    return fields
