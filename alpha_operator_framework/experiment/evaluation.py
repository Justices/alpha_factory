"""Pure acceptance rules for completed backtests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestResult, EvaluationRecord, ExperimentBatch


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


def _dominates(left: BacktestResult, right: BacktestResult) -> bool:
    no_worse = (
        left.sharpe >= right.sharpe
        and left.fitness >= right.fitness
        and left.margin >= right.margin
        and left.turnover <= right.turnover
    )
    strictly_better = (
        left.sharpe > right.sharpe
        or left.fitness > right.fitness
        or left.margin > right.margin
        or left.turnover < right.turnover
    )
    return no_worse and strictly_better


def evaluate_batch(batch: ExperimentBatch) -> list[EvaluationRecord]:
    """Apply hard gates then assign deterministic non-dominated Pareto ranks."""
    records = {task_id: evaluate_result(result) for task_id, result in batch.results.items()}
    eligible = [
        result for task_id, result in batch.results.items()
        if records[task_id].verdict == "READY" and not records[task_id].pruned
    ]
    remaining = sorted(eligible, key=lambda result: result.task_id)
    rank = 1
    while remaining:
        frontier = [
            result for result in remaining
            if not any(_dominates(other, result) for other in remaining if other.task_id != result.task_id)
        ]
        for result in frontier:
            current = records[result.task_id]
            records[result.task_id] = EvaluationRecord(result.task_id, current.verdict, rank, current.pruned)
        frontier_ids = {result.task_id for result in frontier}
        remaining = [result for result in remaining if result.task_id not in frontier_ids]
        rank += 1
    return [records[task_id] for task_id in sorted(records)]
