"""Offline sandbox prefilter."""

from __future__ import annotations

from typing import Any, Sequence


def sandbox_prefilter(tasks: Sequence[Any], market_data: Any = None, min_coverage: float = 0.1, min_abs_ic: float = 0.005, min_sharpe: float = 0.1) -> tuple[list[Any], list[Any]]:
    from alpha_operator_framework.domain.sandbox import SandboxEngine

    engine = SandboxEngine(market_data=market_data)
    passed: list[Any] = []
    rejected: list[Any] = []
    for task in tasks:
        expression = task.expression if hasattr(task, "expression") else (task.get("expression") if isinstance(task, dict) else str(task))
        metrics = engine.evaluate_metrics(expression)
        if not metrics.is_valid or metrics.coverage < min_coverage:
            rejected.append({**task, "sandbox_reason": f"invalid_or_low_coverage: {metrics.error_message}", "metrics": metrics.to_dict()} if isinstance(task, dict) else task)
        elif abs(metrics.rank_ic) >= min_abs_ic or abs(metrics.sharpe) >= min_sharpe:
            passed.append({**task, "sandbox_metrics": metrics.to_dict()} if isinstance(task, dict) else task)
        else:
            rejected.append({**task, "sandbox_reason": "zero_signal", "metrics": metrics.to_dict()} if isinstance(task, dict) else task)
    return passed, rejected
