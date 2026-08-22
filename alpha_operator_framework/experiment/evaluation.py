"""Pure acceptance rules for completed backtests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord


def evaluate_result(result: BacktestResult) -> EvaluationRecord:
    """Classify one normalized result without any platform dependency."""
    pruned = not result.checks_passed or result.sharpe < 0.0 or result.turnover > 0.70
    ready = not pruned and result.sharpe >= 1.0 and result.fitness >= 0.8 and result.margin >= 4.0
    return EvaluationRecord(
        task_id=result.task_id,
        verdict="READY" if ready else "PRUNED" if pruned else "REVIEW",
        pareto_rank=1 if ready else 2,
        pruned=pruned,
    )
