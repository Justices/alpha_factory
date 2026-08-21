"""Unit tests for DatabaseCleaner."""

import pytest
import sqlite3
from pathlib import Path

from alpha_operator_framework.database.cleaner import DatabaseCleaner, clean_alpha_research_db
from alpha_operator_framework.database.repository import AlphaDatabase


def test_database_cleaner_modes(tmp_path):
    """测试数据库清理器的各种清理模式与 VACUUM 释放."""
    test_db = tmp_path / "test_research.db"
    db_inst = AlphaDatabase(db_path=str(test_db))
    db_inst.seed_template_library()

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    # 插入一些测试数据
    cursor.execute("""
        INSERT INTO alpha_expressions (expression_sha, expression, settings, status, created_at, updated_at)
        VALUES ('sha_pass', 'rank(returns)', '{}', 'completed', '2026-08-21', '2026-08-21'),
               ('sha_fail', 'ts_rank(returns, 10)', '{}', 'failed', '2026-08-21', '2026-08-21'),
               ('sha_prune', 'ts_delta(returns, 5)', '{}', 'pruned', '2026-08-21', '2026-08-21'),
               ('sha_pend', 'scale(returns)', '{}', 'pending', '2026-08-21', '2026-08-21')
    """)
    cursor.execute("""
        INSERT INTO alpha_details (alpha_id, expression_sha, expression, sharpe, created_at, updated_at)
        VALUES ('ALPHA_01', 'sha_pass', 'rank(returns)', 1.50, '2026-08-21', '2026-08-21'),
               ('FAILED_01', 'sha_fail', 'ts_rank(returns, 10)', 0.0, '2026-08-21', '2026-08-21')
    """)
    cursor.execute("""
        INSERT INTO alpha_checks (alpha_id, check_name, result, created_at, updated_at)
        VALUES ('ALPHA_01', 'LOW_SHARPE', 'PASS', '2026-08-21', '2026-08-21'),
               ('FAILED_01', 'LOW_SHARPE', 'FAIL', '2026-08-21', '2026-08-21')
    """)
    conn.commit()
    conn.close()

    cleaner = DatabaseCleaner(test_db)

    # 1. 测试 dry-run
    rep_dry = cleaner.clean(mode="failed", dry_run=True, verbose=False)
    assert rep_dry.deleted_expressions == 1
    assert rep_dry.deleted_details == 1
    assert rep_dry.deleted_checks == 1

    # 验证实际未删除
    conn = sqlite3.connect(test_db)
    assert conn.execute("SELECT COUNT(*) FROM alpha_expressions").fetchone()[0] == 4
    conn.close()

    # 2. 实际清理 failed
    rep_exec = cleaner.clean(mode="failed", dry_run=False, verbose=False)
    assert rep_exec.deleted_expressions == 1

    conn = sqlite3.connect(test_db)
    assert conn.execute("SELECT COUNT(*) FROM alpha_expressions WHERE status = 'failed'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alpha_details WHERE alpha_id = 'FAILED_01'").fetchone()[0] == 0
    conn.close()

    # 3. 清理 pruned
    cleaner.clean(mode="pruned", dry_run=False, verbose=False)
    conn = sqlite3.connect(test_db)
    assert conn.execute("SELECT COUNT(*) FROM alpha_expressions WHERE status = 'pruned'").fetchone()[0] == 0
    conn.close()

    # 4. 全量清理 all_data
    cleaner.clean(mode="all_data", dry_run=False, verbose=False)
    conn = sqlite3.connect(test_db)
    assert conn.execute("SELECT COUNT(*) FROM alpha_expressions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alpha_details").fetchone()[0] == 0
    # 但模板库保留
    assert conn.execute("SELECT COUNT(*) FROM template_library").fetchone()[0] > 0
    conn.close()
