"""Unit tests for Domain-Specific Repositories and AlphaDatabase composite facade."""

import tempfile
from pathlib import Path
import pytest

from alpha_operator_framework.database import (
    AlphaDatabase,
    AlphaRepository,
    SimulationRepository,
    DatafieldRepository,
    TemplateRepository,
    QueueRepository,
    EventLedgerRepository,
    DatabaseConnectionManager,
)
from alpha_operator_framework.database.models import Template


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
        expr_sha = alpha_repo.compute_sha("ts_rank(close, 10)")
        fetched_expr = alpha_repo.get_expression_by_sha(expr_sha)
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
                id=1,
                name="test_unary_tpl",
                title="Test Unary",
                family="unary",
                template_type="placeholder",
                expression_template="ts_delta({x}, 5)",
                template_index=0,
                fields_per_alpha=1,
            )
        ])
        templates = tpl_repo.list_templates(families=["unary"])
        assert any(t.name == "test_unary_tpl" for t in templates)

        # F. QueueRepository: 优化队列
        q_id = queue_repo.enqueue_optimization("test_alpha_01", "ts_rank(close, 10)", sharpe=1.1, priority=10)
        assert q_id > 0
        popped = queue_repo.pop_optimization_task()
        assert popped is not None
        assert popped["alpha_id"] == "test_alpha_01"
        assert popped["status"] == "optimizing"

        # G. AlphaDatabase Facade: 聚合访问无缝
        assert db.get_total_trial_count() == 1
        assert db.get_simulation_batch(batch_id)["status"] == "created"
        assert "open" in db.get_existing_datafield_ids("USA", 1)

        db.close()
