"""Execution adapter safety tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestTask
from alpha_operator_framework.infrastructure.brain import DryRunGateway, LiveBrainGateway, build_backtest_gateway


def test_dry_run_does_not_construct_live_brain_gateway() -> None:
    gateway = build_backtest_gateway(execute_platform=False)

    assert isinstance(gateway, DryRunGateway)


class FakeSimulator:
    def simulate_batch(self, tasks, settings):
        assert tasks == [{"expression": "rank(close)"}]
        assert settings == {"region": "GBR", "universe": "TOP700"}
        return [{
            "expression": "rank(close)", "alpha_id": "alpha-1", "sharpe": 1.5,
            "fitness": 1.1, "turnover": 0.2, "margin": 5.0, "checks_passed": True,
        }]


def test_live_gateway_normalizes_platform_results_without_importing_live_client() -> None:
    gateway = LiveBrainGateway(simulator=FakeSimulator())
    task = BacktestTask("task-1", "candidate-1", "rank(close)", {"region": "GBR", "universe": "TOP700"}, "key-1")

    result = gateway.run_backtests([task])[0]

    assert result.task_id == "task-1"
    assert result.platform_alpha_id == "alpha-1"
    assert result.checks_passed is True
