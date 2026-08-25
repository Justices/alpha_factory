"""Explicit execution gateways; dry-run never imports live platform code."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Sequence

from alpha_operator_framework.experiment.models import BacktestResult


class DryRunGateway:
    def run_backtests(self, tasks: Sequence[Any]) -> list[Any]:
        return []


class LiveBrainGateway:
    def __init__(self, simulator: Any | None = None) -> None:
        if simulator is None:
            from alpha_operator_framework.platform.platform_simulator import BrainPlatformSimulator

            simulator = BrainPlatformSimulator()
        self._simulator = simulator

    def run_backtests(self, tasks: Sequence[Any]) -> list[BacktestResult]:
        if not tasks:
            return []
        settings = dict(tasks[0].settings)
        raw_results = self._simulator.simulate_batch(
            [{"expression": task.expression} for task in tasks],
            settings,
        )
        if len(raw_results) != len(tasks):
            raise RuntimeError("Platform returned a result count different from the submitted task count")
        return [self._normalize(task, raw) for task, raw in zip(tasks, raw_results)]

    @staticmethod
    def _normalize(task: Any, raw: Any) -> BacktestResult:
        def value(name: str, default: Any = None) -> Any:
            return raw.get(name, default) if isinstance(raw, Mapping) else getattr(raw, name, default)

        alpha_id = value("alpha_id")
        failed_checks = value("failed_checks", []) or []
        error = value("error") or ("; ".join(map(str, failed_checks)) if str(alpha_id or "").startswith("FAILED_") else None)
        checks_passed = bool(value("checks_passed", value("is_valid", False)))
        return BacktestResult(
            task_id=task.task_id,
            expression=task.expression,
            sharpe=float(value("sharpe", 0.0)),
            fitness=float(value("fitness", 0.0)),
            turnover=float(value("turnover", 0.0)),
            margin=float(value("margin", 0.0)),
            checks_passed=checks_passed,
            platform_alpha_id=str(alpha_id) if alpha_id else None,
            self_correlation=value("sc_value", value("self_correlation")),
            production_correlation=value("pc_value", value("production_correlation")),
            error=str(error) if error else None,
            raw_details=value("raw_details") if isinstance(value("raw_details"), Mapping) else None,
        )


def build_backtest_gateway(*, execute_platform: bool) -> DryRunGateway | LiveBrainGateway:
    return LiveBrainGateway() if execute_platform else DryRunGateway()
