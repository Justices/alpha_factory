import tempfile
from pathlib import Path
import pytest

from alpha_operator_framework.ddd.domain.field_research.models import FieldSnapshot, FieldUniverse
from alpha_operator_framework.ddd.domain.candidate_exploration.models import (
    Candidate,
    PrePruneDecision,
    ResearchPolicy,
    SelectionDecision,
    SelectionRound,
)
from alpha_operator_framework.ddd.domain.experiment_governance.models import (
    BacktestTask,
    EvaluationRecord,
    ExperimentBatch,
    NormalizedBacktestResult,
    PostPruneDecision,
)
from alpha_operator_framework.ddd.domain.knowledge_and_submission.models import (
    KnowledgeBase,
    PruneRuleEvidence,
    SignalDistillationEvidence,
)
from alpha_operator_framework.ddd.infrastructure.persistence.sqlite_repositories import SqliteDddRepository


def test_sqlite_field_universe_persistence():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_ddd.db"
        repo = SqliteDddRepository(db_path)

        fu = FieldUniverse(region="GBR", universe="TOP700")
        fu.register_snapshot(FieldSnapshot(field_id="f1", dataset_id="ds1", coverage=0.95))
        repo.save_universe(fu)

        loaded = repo.load_universe("GBR", "TOP700")
        assert loaded is not None
        assert "f1" in loaded.snapshots
        assert loaded.snapshots["f1"].coverage == 0.95


def test_sqlite_selection_round_persistence():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_ddd.db"
        repo = SqliteDddRepository(db_path)

        policy = ResearchPolicy(region="GBR", universe="TOP700", selection_algorithm="stratified")
        sr = SelectionRound(round_id="r100", policy=policy, seed=42, status="SELECTED")
        cand = Candidate(candidate_id="c1", expression="rank(close)", family="mom", fields=["close"])
        sr.add_candidate(cand)
        sr.record_pre_prune(PrePruneDecision(candidate_id="c1", is_rejected=False, reason_code="PASS"))
        sr.record_selection(
            SelectionDecision(
                candidate_id="c1",
                is_selected=True,
                score_components={"score": 1.0},
                algorithm="stratified",
                policy_version="1.0.0",
                seed=42,
                reason="Quota match",
            )
        )
        repo.save_round(sr)

        loaded = repo.load_round("r100")
        assert loaded is not None
        assert loaded.round_id == "r100"
        assert "c1" in loaded.candidate_pool
        assert loaded.selection_decisions["c1"].is_selected is True


def test_sqlite_experiment_batch_persistence():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_ddd.db"
        repo = SqliteDddRepository(db_path)

        batch = ExperimentBatch(batch_id="b1", idempotency_key="k1", status="COMPLETED")
        task = BacktestTask("t1", "c1", "rank(close)", 12, {"region": "GBR"}, "key_t1")
        res = NormalizedBacktestResult("t1", "a1", "rank(close)", True, 1.35, 1.1, 0.2, 0.15, 0.05, True)
        batch.add_task(task)
        batch.record_result(res)
        batch.record_post_prune(PostPruneDecision("t1", False, "PASS"))
        batch.record_evaluation(EvaluationRecord("t1", "READY", 1.2, {"sharpe_gate": True}))
        repo.save_batch(batch)

        loaded = repo.load_batch("b1")
        assert loaded is not None
        assert "t1" in loaded.results
        assert loaded.results["t1"].sharpe == 1.35
        assert loaded.evaluations["t1"].verdict == "READY"


def test_sqlite_knowledge_base_persistence():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_ddd.db"
        repo = SqliteDddRepository(db_path)

        kb = KnowledgeBase()
        kb.register_template(SignalDistillationEvidence("tpl1", "rank({a})", ["rank(close)"], 1, 1.4))
        kb.register_prune_rule(PruneRuleEvidence("ts_delta(ts_delta(", "prefix", "Noise", 0.9, 10))
        repo.save_knowledge(kb)

        loaded = repo.load_knowledge()
        assert loaded is not None
        assert "tpl1" in loaded.templates
        assert "ts_delta(ts_delta(" in loaded.prune_rules