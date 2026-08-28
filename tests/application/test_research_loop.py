from __future__ import annotations

from dataclasses import dataclass

from alpha_operator_framework.application.research_cycle import ResearchCycleSummary
from alpha_operator_framework.application.research_loop import ResearchLoopCoordinator
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.optimization import CompletedExpression
from alpha_operator_framework.research.round import Candidate, ResearchPolicy
from alpha_operator_framework.research.strategies import StrategyStatus
from alpha_operator_framework.research.strategy_config import (
    ConstructionPlan,
    ConstructionStrategyConfig,
    StructuralConstraint,
)


SETTINGS = {
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 8,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
}


def _plan(*strategy_ids):
    return ConstructionPlan(tuple(
        ConstructionStrategyConfig(
            strategy_id=strategy_id,
            kind="database_template",
            families=("family",),
            order_depth=StructuralConstraint(exact=1),
            field_count=StructuralConstraint(exact=1),
            quota_per_leaf_family=8,
            source="raw_fields",
        )
        for strategy_id in strategy_ids
    ))


def _candidate(index, family, strategy="database"):
    return Candidate(
        f"candidate-{index}",
        f"rank(field_{index})",
        family,
        (f"field_{index}",),
        ("rank",),
        "rank",
        origin_strategy=strategy,
        leaf_family=family,
        order_depth=1,
        field_count=1,
    )


class LoopDatabase:
    def __init__(self, candidates):
        self.pending = list(candidates)
        self.completed = []
        self.selected = {}
        self.task_status = ""

    def load_unbacktested_research_candidates(self, _settings):
        return list(self.pending)

    def selected_counts_by_family(self, _task_id):
        counts = {}
        for candidate in self.selected.values():
            counts[candidate.family] = counts.get(candidate.family, 0) + 1
        return counts

    def next_task_round_sequence(self, _task_id):
        return len({round_id for round_id, _ in self.selected}) + 1

    def save_construction_task(self, _task_id, _settings, _plan, _seed, status, _error=""):
        self.task_status = status

    def load_completed_expression_results(self, _settings):
        return list(self.completed)

    def get_result_prune_rules(self, _settings):
        return []

    def upsert_result_prune_rule(self, *_args):
        return None

    def prune_unbacktested_matching(self, _settings, _rules):
        return []

    def list_templates(self, *, active_only=True):
        return []


@dataclass
class LoopRuntime:
    alpha_database: LoopDatabase
    knowledge_base: KnowledgeBase

    def __post_init__(self):
        self.planned = {}
        self.experiment_repository = None

    def plan(self, request):
        candidates = list(request.candidates)
        self.planned[request.round_id] = candidates
        for candidate in candidates:
            self.alpha_database.selected[(request.round_id, candidate.candidate_id)] = candidate
        return ResearchCycleSummary("SUBMITTED", request.round_id, [])

    def process_round(self, round_id):
        candidates = self.planned[round_id]
        selected_ids = {candidate.candidate_id for candidate in candidates}
        self.alpha_database.pending = [
            candidate for candidate in self.alpha_database.pending
            if candidate.candidate_id not in selected_ids
        ]
        self.alpha_database.completed.extend(
            CompletedExpression(
                candidate.expression,
                candidate.fields,
                0.5,
                0.5,
                True,
                candidate.candidate_id,
                candidate.family,
            )
            for candidate in candidates
        )
        return ResearchCycleSummary("COMPLETED", round_id, [], completed_backtests=len(candidates))


def test_loop_applies_eight_per_leaf_family_and_eight_per_platform_shard() -> None:
    first_family = "database_template/family-a/depth-1/fields-1"
    second_family = "database_template/family-b/depth-1/fields-1"
    candidates = [*[
        _candidate(index, first_family) for index in range(10)
    ], *[
        _candidate(index + 20, second_family) for index in range(4)
    ]]
    runtime = LoopRuntime(LoopDatabase(candidates), KnowledgeBase())
    policy = ResearchPolicy("USA", "TOP3000", 16, **{
        key: value for key, value in SETTINGS.items() if key not in {"region", "universe"}
    })

    summary = ResearchLoopCoordinator(runtime).run(
        policy,
        (),
        candidates,
        construction_plan=_plan("database"),
        seed=7,
        execute=True,
        base_round_id="task",
    )

    assert summary.status == "EXHAUSTED"
    assert [len(batch) for batch in runtime.planned.values()] == [8, 4]
    assert runtime.alpha_database.selected_counts_by_family("task") == {
        first_family: 8,
        second_family: 4,
    }


def test_next_shard_round_robins_leaf_families_and_respects_existing_counts() -> None:
    family_a = "database_template/a/depth-1/fields-1"
    family_b = "database_template/b/depth-1/fields-1"
    candidates = [
        *[_candidate(index, family_a) for index in range(6)],
        *[_candidate(index + 10, family_b) for index in range(6)],
    ]

    shard = ResearchLoopCoordinator._next_shard(candidates, _plan("database"), {family_a: 7})

    assert len(shard) == 7
    assert sum(candidate.family == family_a for candidate in shard) == 1
    assert sum(candidate.family == family_b for candidate in shard) == 6


def test_loop_reports_requested_strategy_failure_after_preserving_other_work() -> None:
    runtime = LoopRuntime(LoopDatabase([]), KnowledgeBase())
    policy = ResearchPolicy("USA", "TOP3000", 0, **{
        key: value for key, value in SETTINGS.items() if key not in {"region", "universe"}
    })

    summary = ResearchLoopCoordinator(runtime).run(
        policy,
        (),
        (),
        construction_plan=_plan("database"),
        seed=7,
        execute=True,
        base_round_id="task",
        strategy_statuses=(StrategyStatus("database", "database_template", "FAILED", error="boom"),),
    )

    assert summary.status == "PARTIAL_FAILED"
    assert runtime.alpha_database.task_status == "PARTIAL_FAILED"
