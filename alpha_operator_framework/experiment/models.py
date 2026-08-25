"""Pure facts collected for one submitted experiment batch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from alpha_operator_framework.research.round import Candidate, ResearchPolicy
from .lifecycle import BatchState, BatchTransition


@dataclass(frozen=True)
class BacktestTask:
    task_id: str
    candidate_id: str
    expression: str
    settings: Mapping[str, object]
    idempotency_key: str
    attempts: int = 0
    next_retry_at: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class BacktestResult:
    task_id: str
    expression: str
    sharpe: float
    fitness: float
    turnover: float
    margin: float
    checks_passed: bool
    platform_alpha_id: str | None = None
    self_correlation: float | None = None
    production_correlation: float | None = None
    error: str | None = None
    raw_details: Mapping[str, object] | None = None


@dataclass(frozen=True)
class EvaluationRecord:
    task_id: str
    verdict: str
    pareto_rank: int
    pruned: bool


@dataclass(frozen=True)
class MutationProposal:
    parent_task_id: str
    expression: str
    mutation_kind: str


@dataclass
class ExperimentBatch:
    batch_id: str
    idempotency_key: str
    state: BatchState = BatchState.PLANNED
    storage_batch_id: int | None = None
    tasks: dict[str, BacktestTask] = field(default_factory=dict)
    results: dict[str, BacktestResult] = field(default_factory=dict)
    evaluations: dict[str, EvaluationRecord] = field(default_factory=dict)
    transitions: list[BatchTransition] = field(default_factory=list)

    def create_tasks(self, cohort: Sequence[Candidate], policy: ResearchPolicy) -> list[BacktestTask]:
        created: list[BacktestTask] = []
        settings = {"region": policy.region, "universe": policy.universe, "delay": policy.delay,
                    "decay": policy.decay, "neutralization": policy.neutralization,
                    "truncation": policy.truncation}
        for index, candidate in enumerate(cohort):
            task = BacktestTask(
                task_id=f"{self.batch_id}:{index}",
                candidate_id=candidate.candidate_id,
                expression=candidate.expression,
                settings=settings,
                idempotency_key=f"{self.idempotency_key}:{index}",
            )
            self.tasks[task.task_id] = task
            created.append(task)
        return created

    def record_result(self, result: BacktestResult) -> None:
        self.results[result.task_id] = result

    def record_evaluation(self, evaluation: EvaluationRecord) -> None:
        self.evaluations[evaluation.task_id] = evaluation

    def record_retry(self, task_ids: Sequence[str], *, next_retry_at: str, error: str) -> None:
        """Replace immutable task facts with one durable retry attempt."""
        for task_id in task_ids:
            task = self.tasks[task_id]
            self.tasks[task_id] = BacktestTask(
                task_id=task.task_id,
                candidate_id=task.candidate_id,
                expression=task.expression,
                settings=task.settings,
                idempotency_key=task.idempotency_key,
                attempts=task.attempts + 1,
                next_retry_at=next_retry_at,
                last_error=error,
            )

    def mutation_parents(self) -> list[BacktestResult]:
        return [
            result
            for task_id, result in self.results.items()
            if (evaluation := self.evaluations.get(task_id))
            and evaluation.verdict == "READY"
            and not evaluation.pruned
            and evaluation.pareto_rank == 1
        ]
