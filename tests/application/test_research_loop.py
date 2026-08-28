from __future__ import annotations

from dataclasses import dataclass

from alpha_operator_framework.application.research_cycle import ResearchCycleSummary
from alpha_operator_framework.application.research_loop import ResearchLoopCoordinator
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.optimization import CompletedExpression
from alpha_operator_framework.research.round import Candidate, ResearchPolicy


SETTINGS = {
    "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
    "neutralization": "SUBINDUSTRY", "truncation": 0.08,
}


class LoopDatabase:
    def __init__(self) -> None:
        self.pending: list[Candidate] = []
        self.cataloged_candidate_ids: set[str] = set()
        self.completed: list[CompletedExpression] = []
        self.lineage: set[tuple[str, str, str]] = set()
        self.templates = (
            Template(name="order", family="unary", expression_template="ts_rank({a}, 22)", slot_count=1),
            Template(name="dimension", family="binary", expression_template="{a} - {b}", slot_count=2),
        )

    def load_unbacktested_research_candidates(self, _settings):
        return list(self.pending)

    def list_templates(self, *, active_only=True):
        return list(self.templates)

    def insert_expression(self, *_args, **_kwargs):
        return 1

    def catalog_research_candidates(self, _round_id, candidates, _settings):
        for candidate in candidates:
            if candidate.candidate_id in self.cataloged_candidate_ids:
                continue
            self.cataloged_candidate_ids.add(candidate.candidate_id)
            self.pending.append(candidate)

    def compute_alpha_sha(self, expression, _settings):
        return expression

    def record_optimization_lineage(self, _settings, parent, child, stage):
        key = (parent, child, stage)
        if key in self.lineage:
            return False
        self.lineage.add(key)
        return True

    def load_completed_expression_results(self, _settings):
        return list(self.completed)

    def get_result_prune_rules(self, _settings):
        return []

    def prune_unbacktested_matching(self, _settings, _rules):
        return []


@dataclass
class LoopRuntime:
    alpha_database: LoopDatabase
    knowledge_base: KnowledgeBase

    def __post_init__(self) -> None:
        self.planned: dict[str, list[Candidate]] = {}

    def plan(self, request):
        self.planned[request.round_id] = list(request.candidates)
        return ResearchCycleSummary("SUBMITTED", request.round_id, [])

    def process_round(self, round_id):
        candidates = self.planned[round_id]
        self.alpha_database.pending = [candidate for candidate in self.alpha_database.pending if candidate not in candidates]
        self.alpha_database.completed.extend(
            CompletedExpression(candidate.expression, candidate.fields, 1.3, 0.9, True, candidate.expression, candidate.family)
            for candidate in candidates
        )
        return ResearchCycleSummary("COMPLETED", round_id, [], completed_backtests=len(candidates))


def test_loop_prioritizes_order2_then_dimension2_before_exhaustion() -> None:
    runtime = LoopRuntime(LoopDatabase(), KnowledgeBase())
    base = Candidate("base", "rank(close)", "base", ("close",), ("rank",), "base")
    fields = (
        FieldSpec("close", "pv", "MATRIX", category="price"),
        FieldSpec("open", "pv", "MATRIX", category="price"),
    )
    policy = ResearchPolicy("USA", "TOP3000", 20, family_quotas={"base": 20}, **{key: value for key, value in SETTINGS.items() if key not in {"region", "universe"}})

    summary = ResearchLoopCoordinator(runtime).run(policy, fields, [base], seed=7, execute=True)

    assert summary.status == "EXHAUSTED"
    assert [candidates[0].family for candidates in runtime.planned.values()] == [
        "base", "optimization_order2", "optimization_dimension2",
    ]


def test_each_loop_round_has_at_most_eight_tasks_across_families() -> None:
    candidates = [
        Candidate(f"candidate-{index}", f"rank(field_{index})", f"family-{index % 3}", (f"field_{index}",), ("rank",), "base")
        for index in range(12)
    ]
    policy = ResearchPolicy("USA", "TOP3000", 60, family_quotas={"legacy": 20}, **{
        key: value for key, value in SETTINGS.items() if key not in {"region", "universe"}
    })

    sliced = ResearchLoopCoordinator._policy_for_candidates(policy, candidates)

    assert sliced.max_backtests == 8
    assert sum(sliced.family_quotas.values()) == 8
