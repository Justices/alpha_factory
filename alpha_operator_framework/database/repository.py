"""Alpha 统一数据库聚合门面 (Unified Database Facade & Aggregate Repository).

基于 DDD 领域驱动设计，通过复合继承/组合聚合 6 大核心领域仓储：
  1. AlphaRepository: 表达式规范化、指纹去重、18 Checks、IS/OOS 绩效与分层采样
  2. SimulationRepository: 仿真批次、任务关联与进度轮询
  3. DatafieldRepository: 平台字段元数据、缺失增量发现与单字段/配对/算子信号自学习
  4. TemplateRepository: 模板种子库、负向淘汰规则与模式过滤
  5. QueueRepository: 优化任务优先队列、达标提交候选池与 SuperAlpha 组合池
  6. EventLedgerRepository: 只追加写事件溯源流与多重检验试验账本

为全系统（EventStore、TrialLedger、ResearchPipeline、Orchestrator、CLI）提供 100% 向下兼容的统一入口。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .base import (
    BaseRepository,
    _num,
    _check_entry,
    _extract_pc_sc,
    submission_wf_stage,
    _isomorphic_fingerprint,
)
from .config import get_database_path, DEFAULT_SQLITE_PATH
from .connection import DatabaseConnectionManager
from .models import AlphaDetail, AlphaExpression, DataField, Template, WF_STAGES
from .repositories import (
    AlphaRepository,
    SimulationRepository,
    DatafieldRepository,
    TemplateRepository,
    QueueRepository,
    EventLedgerRepository,
)
from alpha_operator_framework.domain.evaluation import count_failed_gates


def persist_workflow_row(
    db: "AlphaDatabase",
    row: Dict[str, Any],
    settings: Dict,
    stage: str = "",
    status: str = "pending"
) -> Optional[str]:
    """把单条工作流结果行持久化到数据库 (兼容性辅助函数)."""
    if not isinstance(row, dict):
        return None

    alpha_id = row.get("alpha_id") or row.get("id")
    regular = row.get("regular") if isinstance(row, dict) else None
    expression = regular.get("code") if isinstance(regular, dict) else None
    expression = expression or row.get("expression") or ""

    if not alpha_id or not expression:
        return None

    db.insert_expression(expression, settings)
    db.save_result_with_checks(alpha_id, row, settings)
    return alpha_id


class AlphaDatabase(
    AlphaRepository,
    SimulationRepository,
    DatafieldRepository,
    TemplateRepository,
    QueueRepository,
    EventLedgerRepository,
):
    """Alpha 统一数据库聚合门面 (Composite Facade)."""

    DEFAULT_DB_PATH = DEFAULT_SQLITE_PATH

    def __init__(
        self,
        db_path: Optional[Union[str, Path, DatabaseConnectionManager]] = None,
        timeout: float = 30.0,
        wal_mode: bool = True,
    ):
        """初始化统一数据库."""
        super().__init__(db_path=db_path, timeout=timeout, wal_mode=wal_mode)
        self._init_database()

    def _init_database(self) -> None:
        """初始化数据库核心表结构 (幂等 DDL)."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='alpha_submission_candidates'"
            ).fetchone()
            if row and row[0] > 0:
                return
        except Exception:
            pass

        cursor = conn.cursor()

        # 1. event_log 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_log (
            global_offset INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            stream_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            payload TEXT NOT NULL,
            payload_ref TEXT,
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_stream ON event_log (stream_id, global_offset)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON event_log (event_type, global_offset)")

        # 2. trial_ledger 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trial_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trial_id TEXT NOT NULL UNIQUE,
            expression TEXT NOT NULL,
            family TEXT NOT NULL DEFAULT 'default',
            region TEXT NOT NULL DEFAULT 'GBR',
            universe TEXT NOT NULL DEFAULT 'TOP700',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trial_family ON trial_ledger (family)")

        # 3. alpha_expressions 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_expressions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expression_sha TEXT NOT NULL UNIQUE,
            expression TEXT NOT NULL,
            expression_origin TEXT DEFAULT '',
            settings TEXT,
            batch_id INTEGER,
            fields TEXT,
            status TEXT DEFAULT 'pending',
            first_operator TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_sha ON alpha_expressions (expression_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_status ON alpha_expressions (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_batch_id ON alpha_expressions (batch_id)")

        # 4. alpha_details 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpha_id TEXT NOT NULL UNIQUE,
            expression_sha TEXT NOT NULL,
            alpha_sha TEXT NOT NULL DEFAULT '',
            expression TEXT NOT NULL,
            region TEXT NOT NULL,
            universe TEXT NOT NULL,
            delay INTEGER NOT NULL,
            decay REAL NOT NULL,
            neutralization TEXT NOT NULL,
            truncation REAL NOT NULL,
            sharpe REAL NOT NULL,
            fitness REAL NOT NULL,
            turnover REAL NOT NULL,
            margin REAL NOT NULL,
            pnl REAL,
            returns REAL,
            drawdown REAL,
            long_count INTEGER,
            short_count INTEGER,
            grade TEXT,
            stage_platform TEXT,
            status_platform TEXT,
            wf_stage TEXT NOT NULL DEFAULT 'pending_validation',
            sc_result TEXT,
            sc_value REAL,
            pc_result TEXT,
            pc_value REAL,
            checks_json TEXT,
            ra_failed INTEGER NOT NULL DEFAULT 0,
            ppa_failed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_details_alpha_id ON alpha_details (alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_details_sharpe ON alpha_details (sharpe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_details_wf_stage ON alpha_details (wf_stage)")

        # 5. alpha_checks 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_checks (
            alpha_id TEXT NOT NULL,
            check_name TEXT NOT NULL,
            result TEXT,
            "limit" REAL,
            value REAL,
            extra_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (alpha_id, check_name)
        )
        """)

        # 6. datafields 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS datafields (
            field_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL DEFAULT '',
            dataset_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'MATRIX',
            region TEXT NOT NULL,
            delay INTEGER NOT NULL DEFAULT 1,
            universes_json TEXT NOT NULL DEFAULT '[]',
            coverage REAL DEFAULT 0.0,
            date_coverage REAL DEFAULT 0.0,
            user_count INTEGER DEFAULT 0,
            alpha_count INTEGER DEFAULT 0,
            category TEXT NOT NULL DEFAULT '',
            expression_shas_json TEXT NOT NULL DEFAULT '[]',
            last_fetched_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (field_id, dataset_id, region, delay)
        )
        """)

        # 7. field_signal_stats 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS field_signal_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL,
            universe TEXT NOT NULL DEFAULT '',
            delay INTEGER NOT NULL DEFAULT 1,
            round INTEGER NOT NULL DEFAULT 0,
            trials INTEGER NOT NULL DEFAULT 0,
            signal_count INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL NOT NULL DEFAULT 0.0,
            avg_sharpe REAL NOT NULL DEFAULT 0.0,
            max_sharpe REAL NOT NULL DEFAULT 0.0,
            min_sharpe REAL NOT NULL DEFAULT 0.0,
            avg_fitness REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(field_id, dataset_id, region, universe, delay, round)
        )
        """)

        # 8. pair_signal_stats 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pair_signal_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_spec TEXT NOT NULL,
            pair_kind TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL,
            universe TEXT NOT NULL DEFAULT '',
            delay INTEGER NOT NULL DEFAULT 1,
            round INTEGER NOT NULL DEFAULT 0,
            trials INTEGER NOT NULL DEFAULT 0,
            signal_count INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL NOT NULL DEFAULT 0.0,
            avg_sharpe REAL NOT NULL DEFAULT 0.0,
            max_sharpe REAL NOT NULL DEFAULT 0.0,
            min_sharpe REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(pair_spec, region, universe, delay, round)
        )
        """)

        # 9. operator_signal_stats 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS operator_signal_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT NOT NULL,
            region TEXT NOT NULL,
            universe TEXT NOT NULL DEFAULT '',
            delay INTEGER NOT NULL DEFAULT 1,
            round INTEGER NOT NULL DEFAULT 0,
            trials INTEGER NOT NULL DEFAULT 0,
            signal_count INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL NOT NULL DEFAULT 0.0,
            avg_sharpe REAL NOT NULL DEFAULT 0.0,
            max_sharpe REAL NOT NULL DEFAULT 0.0,
            min_sharpe REAL NOT NULL DEFAULT 0.0,
            avg_fitness REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(operator, region, universe, delay, round)
        )
        """)

        # 10. template_prune_rules 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS template_prune_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            pattern_type TEXT NOT NULL DEFAULT 'prefix',
            family TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'static',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(pattern, pattern_type)
        )
        """)

        # 11. template_library 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS template_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            family TEXT NOT NULL DEFAULT '',
            template_type TEXT NOT NULL DEFAULT 'placeholder',
            expression_template TEXT NOT NULL,
            template_index INTEGER NOT NULL DEFAULT 0,
            fields_per_alpha INTEGER NOT NULL DEFAULT 0,
            expression_origin TEXT NOT NULL DEFAULT '',
            field_types_json TEXT NOT NULL DEFAULT '[]',
            categories_json TEXT NOT NULL DEFAULT '[]',
            dataset_families_json TEXT NOT NULL DEFAULT '[]',
            placeholders_json TEXT NOT NULL DEFAULT '{}',
            group_slots_json TEXT NOT NULL DEFAULT '[]',
            slot_count INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            example_expression TEXT NOT NULL DEFAULT '',
            settings_hint_json TEXT NOT NULL DEFAULT '{}',
            field_candidates_json TEXT NOT NULL DEFAULT '{}',
            operators_used_json TEXT NOT NULL DEFAULT '[]',
            source_json TEXT NOT NULL DEFAULT '{}',
            parent_template_id INTEGER,
            signal_constraints_json TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 12. simulation_batches 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS simulation_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_batch_id TEXT UNIQUE,
            platform_location TEXT,
            simulation_type TEXT NOT NULL DEFAULT 'REGULAR',
            status TEXT NOT NULL DEFAULT 'created',
            settings_json TEXT NOT NULL,
            requested_count INTEGER NOT NULL DEFAULT 0,
            completed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            progress_json TEXT,
            result_json TEXT,
            error_message TEXT,
            submitted_at TEXT,
            last_polled_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 13. simulation_results 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS simulation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            sequence_no INTEGER NOT NULL,
            expression_sha TEXT NOT NULL,
            alpha_sha TEXT NOT NULL DEFAULT '',
            expression TEXT NOT NULL,
            task_json TEXT NOT NULL DEFAULT '{}',
            decay REAL NOT NULL DEFAULT 0.0,
            platform_child_url TEXT,
            alpha_id TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            result_json TEXT,
            error_message TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(batch_id, sequence_no),
            FOREIGN KEY(batch_id) REFERENCES simulation_batches(id)
        )
        """)

        # 14. super_alpha_candidates 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS super_alpha_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_sha TEXT NOT NULL UNIQUE,
            component_ids_json TEXT NOT NULL,
            selection_name TEXT NOT NULL,
            selection TEXT NOT NULL,
            combo_name TEXT NOT NULL,
            combo TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'prepared',
            alpha_id TEXT,
            result_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 15. alpha_optimization_queue 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_optimization_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpha_id TEXT NOT NULL,
            expression TEXT NOT NULL,
            sharpe REAL DEFAULT 0.0,
            fitness REAL DEFAULT 0.0,
            turnover REAL DEFAULT 0.0,
            margin REAL DEFAULT 0.0,
            failed_checks TEXT,
            failed_ra_count INTEGER DEFAULT 0,
            failed_ppa_count INTEGER DEFAULT 0,
            optimization_hints TEXT,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 16. alpha_submission_candidates 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_submission_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpha_id TEXT NOT NULL UNIQUE,
            expression TEXT NOT NULL,
            sharpe REAL DEFAULT 0.0,
            fitness REAL DEFAULT 0.0,
            turnover REAL DEFAULT 0.0,
            margin REAL DEFAULT 0.0,
            sc_value REAL,
            pc_value REAL,
            local_sc REAL,
            local_sc_grade TEXT,
            robustness_status TEXT,
            robustness_notes TEXT,
            needs_optimization INTEGER DEFAULT 0,
            is_submitted INTEGER DEFAULT 0,
            submitted_at TEXT,
            pyramid_category TEXT,
            pyramid_multiplier REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        conn.commit()


__all__ = [
    "AlphaDatabase",
    "AlphaRepository",
    "SimulationRepository",
    "DatafieldRepository",
    "TemplateRepository",
    "QueueRepository",
    "EventLedgerRepository",
    "AlphaExpression",
    "AlphaDetail",
    "DataField",
    "Template",
    "persist_workflow_row",
]
