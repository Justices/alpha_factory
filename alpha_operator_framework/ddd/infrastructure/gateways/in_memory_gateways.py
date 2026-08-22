"""In-Memory Test Doubles for Platform Gateways."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from ...domain.field_research.models import FieldSnapshot
from ...domain.field_research.ports import FieldCatalogPort
from ...domain.experiment_governance.models import BacktestTask, NormalizedBacktestResult
from ...domain.experiment_governance.ports import BacktestGatewayPort
from ...domain.knowledge_and_submission.models import SubmissionCase
from ...domain.knowledge_and_submission.ports import SubmissionGatewayPort


class InMemoryFieldCatalog(FieldCatalogPort):
    """In-memory catalog provider."""

    def __init__(self, initial_fields: Optional[List[FieldSnapshot]] = None):
        self.fields = list(initial_fields or [])

    def fetch_field_snapshots(self, region: str, universe: str, dataset_ids: Optional[List[str]] = None) -> List[FieldSnapshot]:
        res = [f for f in self.fields if f.region == region]
        if dataset_ids:
            res = [f for f in res if f.dataset_id in dataset_ids]
        return res


class InMemoryBacktestGateway(BacktestGatewayPort):
    """In-memory simulation gateway returning deterministic synthetic backtest metrics."""

    def __init__(self, custom_results: Optional[Dict[str, Dict[str, Any]]] = None):
        self.custom_results = custom_results or {}
        self.submitted_batches: List[List[BacktestTask]] = []

    def submit_and_poll_batch(
        self,
        tasks: List[BacktestTask],
        settings: Dict[str, Any],
        idempotency_key: str,
    ) -> List[NormalizedBacktestResult]:
        self.submitted_batches.append(tasks)
        results: List[NormalizedBacktestResult] = []

        for idx, t in enumerate(tasks):
            custom = self.custom_results.get(t.expression, {})
            shp = custom.get("sharpe", 1.25 if idx % 2 == 0 else 0.15)
            fit = custom.get("fitness", 0.95 if idx % 2 == 0 else 0.10)
            trn = custom.get("turnover", 0.18 if idx % 2 == 0 else 0.35)
            ret = custom.get("returns", 0.14 if idx % 2 == 0 else 0.02)
            dd = custom.get("drawdown", 0.08 if idx % 2 == 0 else 0.25)
            passed = custom.get("checks_passed", True)

            results.append(
                NormalizedBacktestResult(
                    task_id=t.task_id,
                    alpha_id=f"alpha_syn_{idx:03d}",
                    expression=t.expression,
                    is_valid=True,
                    sharpe=shp,
                    fitness=fit,
                    turnover=trn,
                    annualized_return=ret,
                    max_drawdown=dd,
                    checks_passed=passed,
                    failed_checks=[] if passed else ["SUB_UNIVERSE_SHARPE"],
                )
            )

        return results


class DryRunBacktestGateway(BacktestGatewayPort):
    """Planning-only gateway; it must never submit a platform request."""

    def submit_and_poll_batch(
        self,
        tasks: List[BacktestTask],
        settings: Dict[str, Any],
        idempotency_key: str,
    ) -> List[NormalizedBacktestResult]:
        return []


class InMemorySubmissionGateway(SubmissionGatewayPort):
    """In-memory submission gateway."""

    def __init__(self):
        self.submitted_cases: List[SubmissionCase] = []

    def submit_approved_case(self, submission_case: SubmissionCase) -> str:
        self.submitted_cases.append(submission_case)
        return f"platform_submission_{len(self.submitted_cases):04d}"
