"""Real WorldQuant BRAIN Platform Gateway Adapter."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from ....platform.platform_simulator import BrainPlatformSimulator, PlatformAlphaResult
from ....carpet_mining import Task
from ...domain.experiment_governance.models import BacktestTask, NormalizedBacktestResult
from ...domain.experiment_governance.ports import BacktestGatewayPort
from ...domain.knowledge_and_submission.models import SubmissionCase
from ...domain.knowledge_and_submission.ports import SubmissionGatewayPort

logger = logging.getLogger("brain_gateway")


class BrainPlatformGateway(BacktestGatewayPort, SubmissionGatewayPort):
    """Production Gateway Adapter for BRAIN API."""

    def __init__(self, simulator: Optional[BrainPlatformSimulator] = None):
        self.simulator = simulator or BrainPlatformSimulator()

    def submit_and_poll_batch(
        self,
        tasks: List[BacktestTask],
        settings: Dict[str, Any],
        idempotency_key: str,
    ) -> List[NormalizedBacktestResult]:
        logger.info(f"Submitting batch of {len(tasks)} tasks to WorldQuant BRAIN platform (idemp={idempotency_key})...")
        
        sim_tasks = [
            Task(
                family="ddd_batch",
                template_index=0,
                fields_per_alpha=1,
                expression=t.expression,
                decay=t.decay,
            )
            for t in tasks
        ]

        # Use simulator batch execution
        sim_results: List[PlatformAlphaResult] = self.simulator.simulate_batch(
            tasks=sim_tasks,
            settings=settings,
            poll_interval=4.0,
            timeout=300.0,
        )

        normalized: List[NormalizedBacktestResult] = []
        for t, r in zip(tasks, sim_results):
            normalized.append(
                NormalizedBacktestResult(
                    task_id=t.task_id,
                    alpha_id=r.alpha_id or f"syn_{t.task_id}",
                    expression=t.expression,
                    is_valid=r.is_valid,
                    sharpe=r.sharpe if r.is_valid else 0.0,
                    fitness=r.fitness if r.is_valid else 0.0,
                    turnover=r.turnover if r.is_valid else 0.0,
                    annualized_return=r.annualized_return if r.is_valid else 0.0,
                    max_drawdown=r.max_drawdown if r.is_valid else 0.0,
                    checks_passed=r.checks_passed,
                    failed_checks=r.failed_checks,
                    raw_metrics=r.raw_details,
                )
            )

        return normalized

    def submit_approved_case(self, submission_case: SubmissionCase) -> str:
        raise NotImplementedError(
            "BRAIN submission is disabled until this adapter calls and verifies "
            "the real platform submission endpoint."
        )
