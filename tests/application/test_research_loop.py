from __future__ import annotations

from dataclasses import dataclass

from alpha_operator_framework.application.research_cycle import ResearchCycleSummary
from alpha_operator_framework.application.research_loop import ResearchLoopCoordinator
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.optimization import CompletedExpression
from alpha_operator_framework.research.round import Candidate, ResearchPolicy
from alpha_operator_framework.research.strategies import StrategyStatus
from alpha_operator_framework.research.strategy_config import (
    CorrelationPromotionPolicy,
    ConstructionPlan,
    ConstructionStrategyConfig,
    PromotionPolicy,
    PromotionQualityGate,
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


def test_early_stop_skips_enhancement_and_routes_signals_to_terminal_validation() -> None:
    class DecisionDatabase:
        def __init__(self):
            self.decisions = []

        def record_promotion_decision(self, *args):
            self.decisions.append(args)

    strategies = (
        ConstructionStrategyConfig(
            "raw", "raw_first_order", ("first_order",),
            StructuralConstraint(minimum=1, maximum=3), StructuralConstraint(exact=1),
            source="raw_fields", stage=1,
        ),
        ConstructionStrategyConfig(
            "depth", "depth_construction", ("unary",),
            StructuralConstraint(minimum=2, maximum=6), StructuralConstraint(minimum=1, maximum=4),
            source="qualified_candidates", stage=2,
        ),
        ConstructionStrategyConfig(
            "validation", "signal_validation", ("rank_sign",),
            StructuralConstraint(minimum=1, maximum=7), StructuralConstraint(minimum=1, maximum=4),
            source="qualified_candidates", stage=3,
        ),
    )
    plan = ConstructionPlan(
        strategies,
        promotion=PromotionPolicy(
            quality=PromotionQualityGate(min_long_short_sum=20),
            correlation=CorrelationPromotionPolicy(enabled=False),
            early_stop_signal_count=1,
        ),
    )
    row = CompletedExpression(
        "rank(close)", ("close",), 1.5, 1.0, True,
        alpha_sha="sha", origin_strategy="raw", long_count=60, short_count=60,
    )
    database = DecisionDatabase()

    retained, selected, target_stages = ResearchLoopCoordinator(object())._select_promotion_rows(
        "task", database, SETTINGS, [row], plan,
    )

    assert retained == [row]
    assert selected == [row]
    assert target_stages == {"sha": 3}
    assert database.decisions[-1][4:7] == ("early_stop", "signal_target_reached", {"target": 1, "validation_stage": 3})


def test_terminal_template_results_use_shared_pruning_and_only_survivors_are_queued() -> None:
    class DecisionDatabase:
        def __init__(self):
            self.decisions = []
            self.queued = []

        def record_promotion_decision(self, *args):
            self.decisions.append(args)

        def enqueue_optimization_once(self, alpha_id, expression, **kwargs):
            self.queued.append((alpha_id, expression, kwargs))

    plan = _plan("database")
    kept = CompletedExpression(
        "rank(close)", ("close",), 1.5, 1.0, True,
        alpha_sha="kept", origin_strategy="database",
    )
    rejected = CompletedExpression(
        "rank(open)", ("open",), 1.0, 1.0, True,
        alpha_sha="rejected", origin_strategy="database",
    )
    database = DecisionDatabase()

    retained, promoted, target_stages = ResearchLoopCoordinator(object())._select_promotion_rows(
        "task", database, SETTINGS, [kept, rejected], plan,
    )
    ResearchLoopCoordinator._queue_signal_candidates(database, retained)

    assert retained == [kept]
    assert promoted == []
    assert target_stages == {}
    assert [item[0] for item in database.queued] == ["kept"]
    assert database.decisions[0][4:6] == ("reject", "below_parent_gate")
    assert database.decisions[1][4:6] == ("promote", "retain_for_review")


def test_rank_sign_validation_compares_each_child_with_parent() -> None:
    class ValidationDatabase:
        def __init__(self):
            self.updates = []

        def load_signal_validation_results(self, _settings):
            return [
                {"parent_alpha_id": "alpha-parent", "parent_sharpe": 2.0,
                 "child_sharpe": 1.2, "validation_variant": "validation:rank"},
                {"parent_alpha_id": "alpha-parent", "parent_sharpe": 2.0,
                 "child_sharpe": 0.8, "validation_variant": "validation:sign"},
            ]

        def update_candidate_robustness(self, *args):
            self.updates.append(args)

    database = ValidationDatabase()
    ResearchLoopCoordinator._evaluate_signal_validations(database, SETTINGS, ConstructionPlan(tuple()))

    assert database.updates == [
        ("alpha-parent", "fail", "rank/sign below 0.50: rank=0.600, sign=0.400"),
    ]


def test_rank_sign_and_platform_robust_checks_finalize_validation() -> None:
    class ValidationDatabase:
        def __init__(self):
            self.updates = []

        def load_signal_validation_results(self, _settings):
            common = {
                "parent_alpha_id": "alpha-parent", "parent_sharpe": 2.0,
                "robust_total": 2, "robust_passed": 2, "robust_failed": 0,
            }
            return [
                {**common, "child_sharpe": 1.2, "validation_variant": "validation:rank"},
                {**common, "child_sharpe": 1.1, "validation_variant": "validation:sign"},
            ]

        def update_candidate_robustness(self, *args):
            self.updates.append(args)

    database = ValidationDatabase()
    ResearchLoopCoordinator._evaluate_signal_validations(database, SETTINGS, ConstructionPlan(tuple()))

    assert database.updates == [
        ("alpha-parent", "pass", "rank/sign and platform robust checks passed; rank=0.600, sign=0.550"),
    ]
