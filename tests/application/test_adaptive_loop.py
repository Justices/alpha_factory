from dataclasses import replace

from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.research.round import SelectionDecision
from alpha_operator_framework.research.field_loader import load_real_market_fields
from alpha_operator_framework.research.strategy_config import CoveragePolicy
from test_research_loop import LoopRuntime, LoopDatabase, _plan, _candidate, SETTINGS
from alpha_operator_framework.application.research_loop import ResearchLoopCoordinator
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import ResearchPolicy


def test_root_catalog_identity_survives_loading_and_records_reserved_budget(tmp_path):
    db = AlphaDatabase(tmp_path / "research.db")
    c = _candidate(1, "family")
    db.insert_expression(c.expression, SETTINGS, fields=list(c.fields), status="generated")
    db.catalog_research_candidates("root", [c], SETTINGS)
    loaded = db.load_unbacktested_research_candidates(SETTINGS, catalog_round_id="root")
    assert loaded[0].candidate_id == c.candidate_id
    db.record_round_selection("root", [SelectionDecision(loaded[0].candidate_id, True, {}, "test", "test")])
    assert len(db.load_task_candidates("root", selected_only=True)) == 1
    assert db.load_task_candidates("other", selected_only=True) == []
    db.close()


def test_resumed_task_does_not_reset_reserved_budget():
    database = LoopDatabase([_candidate(2, "family")])
    database.load_task_candidates = lambda task, selected_only=False: [_candidate(1, "family")]
    runtime = LoopRuntime(database, KnowledgeBase())
    def unexpected_plan(request):
        raise AssertionError("an exhausted resumed task must not plan new work")
    runtime.plan = unexpected_plan
    plan = replace(_plan("database"), rolling_capacity_queue=True, max_total_backtests=1,
                   coverage=CoveragePolicy(enabled=True))
    result = ResearchLoopCoordinator(runtime).run(ResearchPolicy("USA", "TOP3000", 1), (), (),
        construction_plan=plan, seed=7, execute=True, base_round_id="root")
    assert result.status == "BUDGET_EXHAUSTED"
    assert runtime.planned == {}


def test_field_cap_samples_across_datasets(tmp_path):
    import json
    (tmp_path / "a.json").write_text(json.dumps([{"id": f"a{i}", "type": "MATRIX"} for i in range(20)]))
    (tmp_path / "b.json").write_text(json.dumps([{"id": "b", "type": "MATRIX", "frequency": "quarterly"}]))
    fields = load_real_market_fields(custom_dir=tmp_path, max_fields=2, include_base_fields=False)
    assert {f.dataset_id for f in fields} == {"a", "b"}
    assert next(f.frequency for f in fields if f.id == "b") == "quarterly"


def test_repeated_discovery_preserves_validation_and_correlation(tmp_path):
    from alpha_operator_framework.research.optimization import CompletedExpression
    db = AlphaDatabase(tmp_path / "research.db")
    db.record_submission_candidate("alpha", "rank(x)", robustness_status="pass", pc_value=0.3, sc_value=0.2)
    row = CompletedExpression("rank(x)", ("x",), 1.8, 1.1, True, "sha", "raw_first_order/first", "raw", "alpha")
    ResearchLoopCoordinator._queue_signal_candidates(db, [row])
    saved = db.get_submission_candidates()[0]
    assert saved["robustness_status"] == "pass"
    assert saved["pc_value"] == 0.3 and saved["sc_value"] == 0.2
    db.close()


def test_zero_selection_preserves_unseen_root_candidates(tmp_path):
    from alpha_operator_framework.application.research_cycle import ResearchCycleRequest
    from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime
    from alpha_operator_framework.research.round import KnowledgeSnapshot
    import yaml
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"storage": {"driver": "sqlite", "path": str(tmp_path / "r.db")}}))
    runtime = build_research_runtime(config, execute_platform=False)
    a, b = _candidate(1, "family"), replace(_candidate(2, "family"), template_id="other")
    for c in (a, b):
        runtime.alpha_database.insert_expression(c.expression, SETTINGS, fields=list(c.fields), status="generated")
    runtime.alpha_database.catalog_research_candidates("root", [a, b], SETTINGS)
    summary = runtime.plan(ResearchCycleRequest("batch", 7, ResearchPolicy("USA", "TOP3000", 1),
        KnowledgeSnapshot(0, rejected_templates=(a.template_id,)), [a], True, catalog_round_id="root"))
    assert summary.status == "NO_ELIGIBLE_CANDIDATES"
    remaining = runtime.alpha_database.load_unbacktested_research_candidates(SETTINGS, catalog_round_id="root")
    assert [c.expression for c in remaining] == [b.expression]
    runtime.close()


def test_real_runtime_balanced_feedback_and_restart_budget(tmp_path):
    import yaml
    from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime
    from alpha_operator_framework.experiment.models import BacktestResult
    class Gateway:
        def __init__(self): self.calls = []
        def run_backtests(self, tasks):
            self.calls.append(len(tasks))
            return [BacktestResult(t.task_id, t.expression, 0.7, 0.5, 0.2, 0.001, False,
                                   f"alpha-{t.task_id}") for t in tasks]
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"storage": {"driver": "sqlite", "path": str(tmp_path / "r.db")}}))
    gateway = Gateway()
    runtime = build_research_runtime(config, execute_platform=True, backtest_gateway=gateway)
    pool = [replace(_candidate(i, "family"), template_id=f"template-{i}") for i in range(30)]
    db = runtime.alpha_database
    for c in pool:
        db.insert_expression(c.expression, SETTINGS, fields=list(c.fields), status="generated")
    db.catalog_research_candidates("root", pool, SETTINGS)
    plan = replace(_plan("database"), rolling_capacity_queue=True, max_total_backtests=19,
                   coverage=CoveragePolicy(enabled=True))
    coordinator = ResearchLoopCoordinator(runtime)
    policy = ResearchPolicy("USA", "TOP3000", 19)
    summary = coordinator.run(policy, (), pool, construction_plan=plan, seed=7, execute=True, base_round_id="root")
    assert summary.status == "BUDGET_EXHAUSTED"
    assert gateway.calls == [8, 8, 3]
    assert len(db.load_task_candidates("root", selected_only=True)) == 19
    assert db.next_task_round_sequence("root") == 4
    again = coordinator.run(policy, (), (), construction_plan=plan, seed=7, execute=True, base_round_id="root")
    assert again.status == "BUDGET_EXHAUSTED"
    assert gateway.calls == [8, 8, 3]
    runtime.close()


def test_task_local_feedback_preserves_global_pruning_counterevidence(monkeypatch):
    from alpha_operator_framework.research.optimization import CompletedExpression
    import alpha_operator_framework.application.research_loop as module
    candidate = _candidate(1, "family")
    database = LoopDatabase([candidate])
    global_row = CompletedExpression("rank(global_field)", ("global_field",), 1.5, 1.0, True)
    database.completed = [global_row]
    database.load_task_candidates = lambda task, selected_only=False: [] if selected_only else [candidate]
    runtime = LoopRuntime(database, KnowledgeBase())
    observed = []
    def derive(rows, **kwargs):
        observed.extend(rows)
        return []
    monkeypatch.setattr(module, "derive_consensus_prune_rules", derive)
    plan = replace(_plan("database"), rolling_capacity_queue=True, max_total_backtests=1,
                   coverage=CoveragePolicy(enabled=True))
    ResearchLoopCoordinator(runtime).run(ResearchPolicy("USA", "TOP3000", 1), (), [candidate],
        construction_plan=plan, seed=7, execute=True, base_round_id="root")
    assert global_row in observed
