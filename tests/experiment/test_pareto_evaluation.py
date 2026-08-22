"""Post-backtest Pareto evaluation tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.evaluation import evaluate_batch
from alpha_operator_framework.experiment.models import BacktestResult, ExperimentBatch


def test_dominated_qualified_result_receives_lower_pareto_rank() -> None:
    batch = ExperimentBatch("batch", "key")
    batch.record_result(BacktestResult("strong", "rank(returns)", 1.6, 1.2, 0.20, 6.0, True))
    batch.record_result(BacktestResult("weak", "rank(volume)", 1.2, 0.9, 0.30, 4.5, True))

    records = {record.task_id: record for record in evaluate_batch(batch)}

    assert records["strong"].pareto_rank == 1
    assert records["weak"].pareto_rank == 2
