"""Pure facts collected for one submitted experiment batch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from alpha_operator_framework.research.round import Candidate, ResearchPolicy


@dataclass(frozen=True)
class BacktestTask:
    task_id: str
    candidate_id: str
    expression: str
    settings: Mapping[str, object]
    idempotency_key: str


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
    tasks: dict[str, BacktestTask] = field(default_factory=dict)
    results: dict[str, BacktestResult] = field(default_factory=dict)
    evaluations: dict[str, EvaluationRecord] = field(default_factory=dict)

    def create_tasks(self, cohort: Sequence[Candidate], policy: ResearchPolicy) -> list[BacktestTask]:
        created: list[BacktestTask] = []
        settings = {"region": policy.region, "universe": policy.universe}
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

    def mutation_parents(self) -> list[BacktestResult]:
        return [
            result
            for task_id, result in self.results.items()
            if (evaluation := self.evaluations.get(task_id))
            and evaluation.verdict == "READY"
            and not evaluation.pruned
            and evaluation.pareto_rank == 1
        ]
