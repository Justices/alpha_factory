from __future__ import annotations

from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.research.round import Candidate
from alpha_operator_framework.research.strategies import CandidateProvenance


SETTINGS = {
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 8,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
}


def _provenance(candidate_id, strategy_id, kind, family, priority):
    return CandidateProvenance(
        candidate_id=candidate_id,
        strategy_id=strategy_id,
        strategy_kind=kind,
        leaf_family=family,
        template_id=f"{strategy_id}-template",
        hypothesis_id="",
        parent_ids=(),
        order_depth=1,
        field_count=1,
        seed=7,
        strategy_priority=priority,
    )


def test_candidate_provenance_coexists_and_claims_by_strategy_priority(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "provenance.db")
    candidate = Candidate("candidate", "rank(close)", "legacy", ("close",), ("rank",), "rank")
    db.insert_expression(candidate.expression, SETTINGS, status="generated", fields=list(candidate.fields))
    db.catalog_research_candidates("task-catalog", [candidate], SETTINGS)
    candidate_sha = db.compute_alpha_sha(candidate.expression, SETTINGS)
    second = _provenance(candidate.candidate_id, "depth", "depth_construction", "depth/family/depth-1/fields-1", 1)
    first = _provenance(candidate.candidate_id, "database", "database_template", "database/family/depth-1/fields-1", 0)

    assert db.record_candidate_provenance(SETTINGS, candidate_sha, second) is True
    assert db.record_candidate_provenance(SETTINGS, candidate_sha, first) is True
    assert db.record_candidate_provenance(SETTINGS, candidate_sha, first) is False

    records = db.load_candidate_provenance(SETTINGS, candidate_sha)
    pending = db.load_unbacktested_research_candidates(SETTINGS)

    assert [record.strategy_id for record in records] == ["database", "depth"]
    assert pending[0].family == first.leaf_family
    assert pending[0].origin_strategy == "database"


def test_generalized_lineage_and_parent_terminal_run_are_idempotent(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "lineage.db")

    assert db.record_construction_lineage(SETTINGS, "parent", "child", "depth_construction", "depth") is True
    assert db.record_construction_lineage(SETTINGS, "parent", "child", "depth_construction", "depth") is False
    assert db.has_construction_lineage(SETTINGS, "parent", "depth") is True
    assert db.has_parent_strategy_run(SETTINGS, "parent", "depth") is False

    db.record_parent_strategy_run(SETTINGS, "parent", "depth", "EXHAUSTED")

    assert db.has_parent_strategy_run(SETTINGS, "parent", "depth") is True


def test_construction_task_and_strategy_status_are_restart_safe(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "task.db")
    plan = {"strategies": [{"id": "database", "kind": "database_template"}]}

    db.save_construction_task("task", SETTINGS, plan, 7, "GENERATING")
    db.save_strategy_outcome("task", "database", "database_template", 0, "GENERATED", 3)
    db.save_construction_task("task", SETTINGS, plan, 7, "EXHAUSTED")

    assert db.construction_task_exists("task") is True
    statuses = db.load_construction_strategy_statuses("task")
    assert [(status.strategy_id, status.status, status.generated_count) for status in statuses] == [
        ("database", "GENERATED", 3),
    ]
