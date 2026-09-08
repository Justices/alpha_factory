"""Unit tests for Domain-Specific Repositories and AlphaDatabase composite facade."""

import json
import tempfile
from pathlib import Path

from alpha_operator_framework.database import (
    AlphaDatabase,
    AlphaRepository,
    SimulationRepository,
    DatafieldRepository,
    TemplateRepository,
    QueueRepository,
    EventLedgerRepository,
)
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.research.round import Candidate


def test_duplicate_platform_check_names_are_deduplicated_without_losing_failure(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "duplicate_checks.db")
    checks = [
        {"name": "LOW_SHARPE", "result": "PASS", "value": 1.6},
        {"name": "LOW_SHARPE", "result": "FAIL", "value": 0.4, "limit": 1.58},
        {"name": "LOW_FITNESS", "result": "PENDING"},
    ]

    db.save_result_with_checks("alpha-duplicate", {"is": {"checks": checks}}, {"region": "GBR"})

    stored = {item["name"]: item for item in db.get_checks("alpha-duplicate")}
    assert set(stored) == {"LOW_SHARPE", "LOW_FITNESS"}
    assert stored["LOW_SHARPE"]["result"] == "FAIL"
    detail = db.query_alphas(limit=1)[0]
    assert json.loads(detail.checks_json) == checks
    db.close()


def test_persisted_alpha_chain_uses_only_alpha_sha() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "alpha_identity_only.db")
        connection = db._get_connection()

        for table_name in ("alpha_expressions", "alpha_details", "simulation_results"):
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}
            assert "alpha_sha" in columns
            assert "expression_sha" not in columns


def test_expression_identity_includes_canonical_backtest_settings() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "expression_identity.db")
        expression = "rank(close)"
        usa = {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 4}
        eur = {"decay": 4, "delay": 1, "universe": "TOP2500", "region": "EUR"}

        db.insert_expression(expression, usa)
        db.insert_expression(expression, eur)

        rows = db.query_expressions(limit=10)
        assert len(rows) == 2
        assert {row.alpha_sha for row in rows} == {
            db.compute_alpha_sha(expression, usa),
            db.compute_alpha_sha(expression, eur),
        }
        db.set_expression_status(expression, "completed", usa)
        assert db.get_expression_by_alpha_sha(db.compute_alpha_sha(expression, usa)).status == "completed"
        assert db.get_expression_by_alpha_sha(db.compute_alpha_sha(expression, eur)).status == "pending"


def test_pruning_status_is_independent_from_completed_backtest_status() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "pruned_status.db")
        expression = "rank(close)"
        db.insert_expression(expression, {"region": "USA"}, status="completed")

        settings = {"region": "USA"}
        db.mark_expressions_pruned([db.compute_alpha_sha(expression, settings)])

        stored = db.get_expression_by_alpha_sha(db.compute_alpha_sha(expression, settings))
        assert stored.status == "completed"
        assert stored.pruning_status == "pruned"


def test_load_unbacktested_research_candidates_keeps_only_active_scope_rows() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "continue_research.db")
        settings = {"region": "USA", "universe": "TOP3000", "delay": 1}
        candidates = [
            Candidate("ready", "rank(close)", "unary", ("close",), ("rank",), "template"),
            Candidate("done", "rank(volume)", "unary", ("volume",), ("rank",), "template"),
        ]
        for candidate in candidates:
            db.insert_expression(candidate.expression, settings, status="generated", fields=list(candidate.fields))
        db.catalog_research_candidates("source-round", candidates, settings)
        db.set_expression_status("rank(volume)", "completed", settings)

        pending = db.load_unbacktested_research_candidates(settings)

        assert [candidate.expression for candidate in pending] == ["rank(close)"]


def test_alpha_pnl_cache_is_idempotent_and_returns_the_latest_payload(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "pnl-cache.db")
    first = {"records": [{"date": "2020-01-01", "pnl": 1.0}]}
    latest = {"records": [{"date": "2020-01-02", "pnl": 2.0}]}

    assert db.get_alpha_pnl_cache("alpha-1") is None
    db.cache_alpha_pnl("alpha-1", first)
    db.cache_alpha_pnl("alpha-1", latest)

    assert db.get_alpha_pnl_cache("alpha-1") == latest
    db.close()


def test_catalog_quota_pruning_is_task_scoped_and_preserves_other_catalogs(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "catalog-quota.db")
    settings = {
        "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
        "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    }
    family = "raw_first_order/first_order/depth-2/fields-1"
    candidates = [
        Candidate(f"candidate-{index}", f"rank(field_{index})", family, (f"field_{index}",), ("rank",), "rank")
        for index in range(5)
    ]
    for candidate in candidates:
        db.insert_expression(candidate.expression, settings, status="generated", fields=list(candidate.fields))
    db.catalog_research_candidates("task-a-catalog", candidates, settings)
    db.catalog_research_candidates("task-b-catalog", candidates, settings)

    assert db.prune_catalog_candidates_beyond_family_quota("task-a-catalog", {family: 2}) == 3
    assert len(db.load_unbacktested_research_candidates(settings, catalog_round_id="task-a-catalog")) == 2
    assert len(db.load_unbacktested_research_candidates(settings, catalog_round_id="task-b-catalog")) == 5
    db.close()


def test_result_prune_rule_only_prunes_active_unbacktested_expressions_in_scope(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "scoped_prune.db")
    usa = {
        "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
        "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    }
    eur = {**usa, "region": "EUR", "universe": "TOP2500"}
    pending = Candidate("pending", "rank(close)", "unary", ("close",), ("rank",), "rank")
    completed = Candidate("completed", "rank(open)", "unary", ("open",), ("rank",), "rank")

    for candidate, settings, status in ((pending, usa, "generated"), (pending, eur, "generated"), (completed, usa, "completed")):
        db.insert_expression(candidate.expression, settings, status=status, fields=list(candidate.fields))
        db.catalog_research_candidates(f"round-{settings['region']}-{candidate.candidate_id}", [candidate], settings)

    db.upsert_result_prune_rule(usa, "rank(", "prefix", "consensus failure")
    pruned = db.prune_unbacktested_matching(usa, db.get_result_prune_rules(usa))

    assert pruned == [db.compute_alpha_sha(pending.expression, usa)]
    assert db.get_expression_by_alpha_sha(db.compute_alpha_sha(pending.expression, usa)).pruning_status == "pruned"
    assert db.get_expression_by_alpha_sha(db.compute_alpha_sha(pending.expression, eur)).pruning_status == "active"
    assert db.get_expression_by_alpha_sha(db.compute_alpha_sha(completed.expression, usa)).status == "completed"
    assert db.get_expression_by_alpha_sha(db.compute_alpha_sha(completed.expression, usa)).pruning_status == "active"


def test_replacing_result_prune_rules_removes_rules_from_an_old_threshold(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "replace-prune-rules.db")
    settings = {
        "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
        "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    }
    db.upsert_result_prune_rule(
        settings, "rank({a})", "abstract_template", "sharpe below 0.8",
    )

    db.replace_result_prune_rules(settings, [{
        "pattern": "ts_rank({a},22)",
        "pattern_type": "abstract_template",
        "reason": "sharpe fails parent gate (> 0.6)",
    }])

    assert db.get_result_prune_rules(settings) == [{
        "pattern": "ts_rank({a},22)",
        "pattern_type": "abstract_template",
        "reason": "sharpe fails parent gate (> 0.6)",
    }]




def test_optimization_lineage_is_idempotent(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "optimization_lineage.db")
    settings = {
        "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
        "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    }

    assert db.record_optimization_lineage(settings, "parent", "child", "order2") is True
    assert db.record_optimization_lineage(settings, "parent", "child", "order2") is False


def test_load_completed_expression_results_returns_metrics_and_candidate_family(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "completed_results.db")
    settings = {
        "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
        "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    }
    candidate = Candidate("candidate", "rank(close)", "base", ("close",), ("rank",), "rank")
    db.insert_expression(candidate.expression, settings, status="completed", fields=list(candidate.fields))
    db.catalog_research_candidates("completed-round", [candidate], settings)
    db.save_result_with_checks("alpha-1", {
        "expression": candidate.expression,
        "is": {
            "sharpe": 1.3, "fitness": 0.9, "turnover": 0.15,
            "margin": 6.5, "pnl": 123.0, "longCount": 60,
            "shortCount": 55, "checks": [],
        },
    }, settings)

    rows = db.load_completed_expression_results(settings)

    assert [(row.expression, row.family, row.sharpe, row.fitness) for row in rows] == [
        ("rank(close)", "base", 1.3, 0.9),
    ]
    assert rows[0].platform_alpha_id == "alpha-1"
    assert (rows[0].turnover, rows[0].margin, rows[0].pnl) == (0.15, 6.5, 123.0)
    assert (rows[0].long_count, rows[0].short_count) == (60, 55)


def test_promotion_decisions_are_idempotent_and_auditable(tmp_path) -> None:
    db = AlphaDatabase(tmp_path / "promotion_decisions.db")
    settings = {
        "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
        "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    }

    db.record_promotion_decision(
        "task", settings, "sha-1", 2, "reject", "multi_channel_corr",
        {"channels": ["sharpe", "fitness", "margin"]},
    )
    db.record_promotion_decision("task", settings, "sha-1", 2, "promote")

    assert db.load_promotion_decisions("task") == [{
        "alpha_sha": "sha-1", "stage": 2, "decision": "promote",
        "reason": "", "details": {},
    }]


def test_domain_repositories_standalone_and_shared_connection():
    """验证领域专用仓储既可独立构造，也可共享底层连接管理器."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_domain.db"
        # 1. 统一初始化 Schema
        db = AlphaDatabase(db_path)

        # 2. 独立仓储使用同一个 ConnectionManager
        alpha_repo = AlphaRepository(db.manager)
        sim_repo = SimulationRepository(db.manager)
        df_repo = DatafieldRepository(db.manager)
        tpl_repo = TemplateRepository(db.manager)
        queue_repo = QueueRepository(db.manager)
        event_repo = EventLedgerRepository(db.manager)

        # A. AlphaRepository: 插入并查询表达式
        expr_id = alpha_repo.insert_expression(
            expression="ts_rank(close, 10)",
            settings={"region": "USA", "universe": "TOP3000"},
            expression_origin="unary_test",
        )
        assert expr_id > 0
        alpha_sha = alpha_repo.compute_alpha_sha("ts_rank(close, 10)", {"region": "USA", "universe": "TOP3000"})
        fetched_expr = alpha_repo.get_expression_by_alpha_sha(alpha_sha)
        assert fetched_expr is not None
        assert fetched_expr.expression == "ts_rank(close, 10)"

        # B. EventLedgerRepository: 追加事件与记录试验
        offset = event_repo.append_event(
            event_id="evt_001",
            stream_id="stream_alpha_1",
            event_type="AlphaDiscovered",
            schema_version=1,
            payload_json='{"alpha_id": "test_01"}',
            payload_ref=None,
            occurred_at="2026-08-21T18:00:00",
            actor="researcher",
            metadata_json="{}",
        )
        assert offset > 0
        events = event_repo.read_events_by_stream("stream_alpha_1")
        assert len(events) == 1
        assert events[0]["event_type"] == "AlphaDiscovered"

        event_repo.record_trial("trial_001", "ts_rank(close, 10)", family="unary", region="USA")
        assert event_repo.get_total_trial_count() == 1
        assert event_repo.get_trial_counts_by_family()["unary"] == 1

        # C. SimulationRepository: 创建批次
        batch_id = sim_repo.create_simulation_batch(
            tasks=[{"expression": "ts_rank(close, 10)"}],
            settings={"region": "USA", "universe": "TOP3000"},
        )
        assert batch_id > 0
        batch = sim_repo.get_simulation_batch(batch_id)
        assert batch["status"] == "created"

        # D. DatafieldRepository: 增删改查字段
        df_repo.upsert_datafield({
            "id": "open",
            "dataset": {"id": "fundamental", "name": "Basic"},
            "region": "USA",
            "delay": 1,
            "universe": "TOP3000",
        })
        existing_fields = df_repo.get_existing_datafield_ids("USA", 1)
        assert "open" in existing_fields

        # E. TemplateRepository: 增改模板
        tpl_repo.upsert_templates([
            Template(
                name="test_custom_unique_tpl_01",
                title="Test Unary",
                family="unary",
                template_type="placeholder",
                expression_template="ts_delta({x}, 5)",
                template_index=99,
                fields_per_alpha=1,
            )
        ])
        templates = tpl_repo.list_templates(names=["test_custom_unique_tpl_01"])
        assert any(t.name == "test_custom_unique_tpl_01" for t in templates)

        # F. QueueRepository: 优化队列
        q_id = queue_repo.enqueue_optimization("test_alpha_01", "ts_rank(close, 10)", sharpe=1.1, priority=10)
        assert q_id > 0
        popped = queue_repo.pop_optimization_task()
        assert popped is not None
        assert popped["alpha_id"] == "test_alpha_01"
        assert popped["status"] == "optimizing"
        assert queue_repo.enqueue_optimization_once("test_alpha_01", "ts_rank(close, 10)") == q_id
        assert len(queue_repo.get_optimization_queue(limit=10)) == 1

        # G. AlphaDatabase Facade: 聚合访问无缝
        assert db.get_total_trial_count() == 1
        assert db.get_simulation_batch(batch_id)["status"] == "created"
        assert "open" in db.get_existing_datafield_ids("USA", 1)

        db.close()
