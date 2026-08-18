"""Alpha数据库模块 — 使用SQLite管理alpha表达式和回测结果.

设计理念:
  1. alpha_expressions: 表达式表,去重存储(基于expression_sha)
  2. alpha_details: 详情表,平铺所有指标便于查询 (含PC/SC/checks)
  3. alpha_checks: 检查子表,存平台全部提交检查项 (1:N, 按地区动态约18种)

基于CSV参考:
  - sim_queue.csv: 模拟队列
  - simulated_alphas_2025-07-29.csv: 模拟结果
"""

import sqlite3
import json
import hashlib
import random
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Sequence
from dataclasses import asdict

from .models import AlphaDetail, AlphaExpression, DataField, Template, WF_STAGES
from alpha_operator_framework.domain.evaluation import count_failed_gates


# ---------------------------------------------------------------------------
# 模块级工具
# ---------------------------------------------------------------------------

def _num(data: Dict, key: str) -> Optional[float]:
    """安全取数值(容忍 None/字符串),取不到返回 None."""
    if not isinstance(data, dict):
        return None
    v = data.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _check_entry(checks: List[Dict], name: str) -> Optional[Dict]:
    """按名字找 check 条目."""
    for c in checks or []:
        if isinstance(c, dict) and c.get("name") == name:
            return c
    return None


def _extract_pc_sc(is_block: Dict, checks: List[Dict]) -> Tuple:
    """提取 PC/SC: 标量优先, fallback 到 checks 里的 value/maxCorrelation.

    Returns:
        (sc_value, pc_value, sc_result, pc_result)
    """
    sc_check = _check_entry(checks, "SELF_CORRELATION")
    pc_check = _check_entry(checks, "PROD_CORRELATION")

    sc_value = _num(is_block, "selfCorrelation")
    pc_value = _num(is_block, "prodCorrelation")
    if sc_value is None and sc_check:
        sc_value = _num(sc_check, "value")
        if sc_value is None:
            sc_value = _num(sc_check, "maxCorrelation")
    if pc_value is None and pc_check:
        pc_value = _num(pc_check, "value")
        if pc_value is None:
            pc_value = _num(pc_check, "maxCorrelation")

    sc_result = (sc_check or {}).get("result")
    pc_result = (pc_check or {}).get("result")
    if sc_result is None:
        sc_result = "PASS" if sc_value is None or sc_value <= 0.7 else "FAIL"
    if pc_result is None:
        pc_result = "PASS" if pc_value is None or pc_value <= 0.7 else "FAIL"

    return sc_value, pc_value, sc_result, pc_result


def submission_wf_stage(sc_result: Optional[str], pc_result: Optional[str]) -> str:
    """SC/PC 判定 → 系统内阶段: 均 PASS/WARNING(或缺失) → 'validated', 否则 → 'needs_optimization'."""
    def _ok(r: Optional[str]) -> bool:
        return r is None or r in ("PASS", "WARNING")
    return "validated" if _ok(sc_result) and _ok(pc_result) else "needs_optimization"


def persist_workflow_row(
    db: "AlphaDatabase",
    row: Dict[str, Any],
    settings: Dict,
    stage: str,
    status: str = "pending"
) -> Optional[str]:
    """把单条工作流结果行持久化到数据库.

    依次: insert_expression → save_result_with_checks。

    ``alpha_details`` 是工作流唯一的回测结果表。

    Args:
        db: AlphaDatabase 实例
        row: 工作流结果行 (形如 {"alpha_id":..., "expression":..., "is":..., "settings":...})
        settings: 回测设置 (会被行内自带 settings 覆盖)
        stage: legacy 参数 (当前不写库)
        status: legacy 参数 (当前不写库); wf_stage 由 save_result_with_checks 默认 + update_wf_stage/mark_alpha_submitted/mark_alpha_failed 管理

    Returns:
        alpha_id; 跳过(无id/无表达式)时返回 None
    """
    if not isinstance(row, dict):
        return None

    alpha_id = row.get("alpha_id") or row.get("id")
    regular = row.get("regular") if isinstance(row, dict) else None
    expression = regular.get("code") if isinstance(regular, dict) else None
    expression = expression or row.get("expression") or ""

    if not alpha_id or not expression:
        return None  # PENDING_NEEDS_PAIR 等无 id / 无表达式行跳过

    db.insert_expression(expression, settings)
    db.save_result_with_checks(alpha_id, row, settings)
    return alpha_id


# ---------------------------------------------------------------------------
# 数据库管理器
# ---------------------------------------------------------------------------

class AlphaDatabase:
    """Alpha数据库管理器."""

    # 默认数据库路径: 项目根目录/data/alpha_research.db
    DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "alpha_research.db"

    def __init__(self, db_path: Optional[str] = None):
        """初始化数据库.

        Args:
            db_path: 数据库文件路径，默认使用 data/alpha_research.db
        """
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self) -> None:
        """显式关闭底层连接 (释放文件句柄, 供测试/短生命周期场景使用)."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _init_database(self):
        """初始化数据库表结构."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 表1: alpha_expressions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_expressions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expression_sha TEXT NOT NULL UNIQUE,
            expression TEXT NOT NULL,
            expression_origin TEXT NOT NULL DEFAULT '',
            settings TEXT NOT NULL,
            batch_id INTEGER,
            fields TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','failed','pruned')),
            first_operator TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 表2: alpha_details
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpha_id TEXT NOT NULL UNIQUE,
            expression_sha TEXT NOT NULL,
            alpha_sha TEXT NOT NULL DEFAULT '',
            expression TEXT NOT NULL,

            -- 回测设置
            region TEXT,
            universe TEXT,
            delay INTEGER DEFAULT 1,
            decay REAL DEFAULT 0.0,
            neutralization TEXT,
            truncation REAL DEFAULT 0.0,

            -- 回测指标
            sharpe REAL DEFAULT 0.0,
            fitness REAL DEFAULT 0.0,
            turnover REAL DEFAULT 0.0,
            margin REAL DEFAULT 0.0,
            pnl REAL DEFAULT 0.0,
            returns REAL DEFAULT 0.0,
            drawdown REAL DEFAULT 0.0,
            long_count INTEGER DEFAULT 0,
            short_count INTEGER DEFAULT 0,

            -- 平台信息
            grade TEXT,
            stage_platform TEXT,
            status_platform TEXT,

            -- 系统内工作流阶段 (pending_validation/validated/submitted/failed/needs_optimization)
            wf_stage TEXT NOT NULL DEFAULT 'pending_validation',

            -- 提交检查指标
            sc_result TEXT,
            sc_value REAL,
            pc_result TEXT,
            pc_value REAL,
            checks_json TEXT,

            -- RA/PPA 失败检查项计数 (参考 WebDataScope failedNumRA/failedNumPPA)
            ra_failed INTEGER NOT NULL DEFAULT 0,
            ppa_failed INTEGER NOT NULL DEFAULT 0,

            -- 时间戳
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 表4: alpha_checks (检查子表, 1:N)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_checks (
            alpha_id TEXT NOT NULL,
            check_name TEXT NOT NULL,
            result TEXT,
            "limit" REAL,
            value REAL,
            extra_json TEXT,        -- year/startDate/endDate/pyramids/themes/effective/multiplier 等
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (alpha_id, check_name)
        )
        """)

        # 有信号的数据字段表 (仅收录被 alpha 用到的字段; universe 聚合为 JSON 数组)
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

        # 字段级信号统计表 (研究闭环 P0 — 第6步沉淀回流到第1步)
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

        # 配对级信号统计表 (研究闭环 P2 — 相反/复合配对的信号沉淀, 第6→2 回流)
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

        # 模板类库表 (对齐 knowledge_base/alpha_templates JSONL schema)
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
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

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

        # 表5: alpha_optimization_queue (待优化的alpha)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_optimization_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpha_id TEXT NOT NULL,
            expression TEXT NOT NULL,

            -- 性能指标快照
            sharpe REAL DEFAULT 0.0,
            fitness REAL DEFAULT 0.0,
            turnover REAL DEFAULT 0.0,
            margin REAL DEFAULT 0.0,

            -- 失败检查项 (JSON数组: [{name, result, value, limit}])
            failed_checks TEXT,
            failed_ra_count INTEGER DEFAULT 0,
            failed_ppa_count INTEGER DEFAULT 0,

            -- 优化建议 (JSON对象)
            optimization_hints TEXT,

            -- 状态
            status TEXT DEFAULT 'pending',     -- pending/optimizing/resolved/abandoned
            priority INTEGER DEFAULT 0,        -- 优先级 (越高越优先)
            retry_count INTEGER DEFAULT 0,

            -- 时间戳
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 表6: alpha_submission_candidates (已达到提交标准的alpha)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alpha_submission_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpha_id TEXT NOT NULL UNIQUE,
            expression TEXT NOT NULL,

            -- 性能详情
            sharpe REAL DEFAULT 0.0,
            fitness REAL DEFAULT 0.0,
            turnover REAL DEFAULT 0.0,
            margin REAL DEFAULT 0.0,
            sc_value REAL,
            pc_value REAL,

            -- 本地预检结果
            local_sc REAL,
            local_sc_grade TEXT,                -- blue/yellow/green

            -- 审计结果
            robustness_status TEXT,              -- pending/pass/fail
            robustness_notes TEXT,

            -- 提交状态
            needs_optimization INTEGER DEFAULT 0,
            is_submitted INTEGER DEFAULT 0,
            submitted_at TEXT,

            -- 金字塔信息
            pyramid_category TEXT,
            pyramid_multiplier REAL,

            -- 时间戳
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # ALTER-guard: 给已存在的 alpha_details 补新列 (fresh DB 自动跳过)
        expression_columns = {r["name"] for r in cursor.execute("PRAGMA table_info(alpha_expressions)")}
        if "expression_origin" not in expression_columns:
            cursor.execute("ALTER TABLE alpha_expressions ADD COLUMN expression_origin TEXT NOT NULL DEFAULT ''")
        for col, decl in (("batch_id", "INTEGER"),
                          ("fields", "TEXT NOT NULL DEFAULT '[]'"),
                          ("status", "TEXT NOT NULL DEFAULT 'pending'"),
                          ("first_operator", "TEXT NOT NULL DEFAULT ''")):
            if col not in expression_columns:
                cursor.execute(f"ALTER TABLE alpha_expressions ADD COLUMN {col} {decl}")

        existing = {r["name"] for r in cursor.execute("PRAGMA table_info(alpha_details)")}
        for col, decl in (("sc_result", "TEXT"), ("sc_value", "REAL"),
                          ("pc_result", "TEXT"), ("pc_value", "REAL"), ("checks_json", "TEXT")):
            if col not in existing:
                cursor.execute(f"ALTER TABLE alpha_details ADD COLUMN {col} {decl}")
        if "alpha_sha" not in existing:
            cursor.execute("ALTER TABLE alpha_details ADD COLUMN alpha_sha TEXT NOT NULL DEFAULT ''")
        if "ra_failed" not in existing:
            cursor.execute("ALTER TABLE alpha_details ADD COLUMN ra_failed INTEGER NOT NULL DEFAULT 0")
        if "ppa_failed" not in existing:
            cursor.execute("ALTER TABLE alpha_details ADD COLUMN ppa_failed INTEGER NOT NULL DEFAULT 0")
        if "wf_stage" not in existing:
            cursor.execute("ALTER TABLE alpha_details ADD COLUMN wf_stage TEXT NOT NULL DEFAULT 'pending_validation'")
        simulation_result_columns = {r["name"] for r in cursor.execute("PRAGMA table_info(simulation_results)")}
        if "alpha_sha" not in simulation_result_columns:
            cursor.execute("ALTER TABLE simulation_results ADD COLUMN alpha_sha TEXT NOT NULL DEFAULT ''")
        if "task_json" not in simulation_result_columns:
            cursor.execute("ALTER TABLE simulation_results ADD COLUMN task_json TEXT NOT NULL DEFAULT '{}'")
        simulation_batch_columns = {r["name"] for r in cursor.execute("PRAGMA table_info(simulation_batches)")}
        if "simulation_type" not in simulation_batch_columns:
            cursor.execute("ALTER TABLE simulation_batches ADD COLUMN simulation_type TEXT NOT NULL DEFAULT 'REGULAR'")
        datafield_columns = {r["name"] for r in cursor.execute("PRAGMA table_info(datafields)")}
        if "category" not in datafield_columns:
            cursor.execute("ALTER TABLE datafields ADD COLUMN category TEXT NOT NULL DEFAULT ''")

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_sha ON alpha_expressions(expression_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_sha ON alpha_details(expression_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_sharpe ON alpha_details(sharpe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_fitness ON alpha_details(fitness)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_stage ON alpha_details(stage_platform)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_wf_stage ON alpha_details(wf_stage)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checks_alpha ON alpha_checks(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checks_name ON alpha_checks(check_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sim_batch_status ON simulation_batches(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sim_result_batch ON simulation_results(batch_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sim_result_alpha ON simulation_results(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sim_result_alpha_sha ON simulation_results(alpha_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_super_candidate_status ON super_alpha_candidates(status)")

        # 新表索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_queue_alpha ON alpha_optimization_queue(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_queue_status ON alpha_optimization_queue(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_queue_priority ON alpha_optimization_queue(priority)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_cand_alpha ON alpha_submission_candidates(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_cand_submitted ON alpha_submission_candidates(is_submitted)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_cand_sharpe ON alpha_submission_candidates(sharpe)")

        # datafields / alpha_expressions 新列索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_datafields_region ON datafields(region)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_datafields_dataset ON datafields(dataset_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_datafields_type ON datafields(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_batch ON alpha_expressions(batch_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_status ON alpha_expressions(status)")

        # template_library 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tpl_family ON template_library(family)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tpl_active ON template_library(active)")

        # field_signal_stats 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_field_signal_hit ON field_signal_stats(region, round, hit_rate DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_field_signal_field ON field_signal_stats(field_id, dataset_id)")

        # pair_signal_stats 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_signal_hit ON pair_signal_stats(region, round, hit_rate DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_signal_spec ON pair_signal_stats(pair_spec)")

        conn.commit()

        # 幂等种子: 4 族模板入模板库 (懒加载, 避循环依赖)
        self.seed_template_library()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))

    def create_simulation_batch(self, tasks: List[Dict[str, Any]], settings: Dict[str, Any],
                                simulation_type: str = "REGULAR") -> int:
        now = self._timestamp()
        conn = self._get_connection()
        cursor = conn.execute(
            """INSERT INTO simulation_batches
            (status, simulation_type, settings_json, requested_count, created_at, updated_at)
            VALUES ('created', ?, ?, ?, ?, ?)""",
            (simulation_type.upper(), self._json(settings), len(tasks), now, now),
        )
        batch_id = int(cursor.lastrowid)
        for sequence_no, task in enumerate(tasks):
            expression = str(task.get("expression") or task.get("candidate_sha") or "")
            if not expression:
                raise ValueError("simulation task requires expression or candidate_sha")
            conn.execute(
                """INSERT INTO simulation_results
                (batch_id, sequence_no, expression_sha, alpha_sha, expression, task_json, decay, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?, ?)""",
                (batch_id, sequence_no, self.compute_sha(expression), self.compute_alpha_sha(expression, settings), expression,
                 self._json(task), float(task.get("decay", settings.get("decay", 0.0))), now, now),
            )
        # 回填 alpha_expressions: 本批次涉及的所有表达式标记待回测并关联批次
        conn.execute(
            """UPDATE alpha_expressions SET batch_id=?, status='pending', updated_at=?
               WHERE expression_sha IN (SELECT expression_sha FROM simulation_results WHERE batch_id=?)""",
            (batch_id, now, batch_id),
        )
        conn.commit()
        return batch_id

    def attach_platform_batch(self, batch_id: int, platform_batch_id: str, platform_location: str) -> None:
        now = self._timestamp()
        self._get_connection().execute(
            """UPDATE simulation_batches SET platform_batch_id=?, platform_location=?, status='submitted',
            submitted_at=?, updated_at=? WHERE id=?""",
            (platform_batch_id, platform_location, now, now, batch_id),
        )
        self._get_connection().commit()

    def record_simulation_progress(self, batch_id: int, progress: Any, *, status: str = "polling",
                                   error_message: str = "") -> None:
        now = self._timestamp()
        self._get_connection().execute(
            """UPDATE simulation_batches SET status=?, progress_json=?, last_polled_at=?,
            error_message=COALESCE(NULLIF(?, ''), error_message), updated_at=? WHERE id=?""",
            (status, self._json(progress), now, error_message, now, batch_id),
        )
        self._get_connection().commit()

    def record_simulation_result(self, batch_id: int, sequence_no: int, *, status: str,
                                 alpha_id: str = "", child_url: str = "", result: Any = None,
                                 error_message: str = "") -> None:
        now = self._timestamp()
        terminal = status in ("completed", "failed")
        self._get_connection().execute(
            """UPDATE simulation_results SET status=?, alpha_id=COALESCE(NULLIF(?, ''), alpha_id),
            platform_child_url=COALESCE(NULLIF(?, ''), platform_child_url), result_json=COALESCE(?, result_json),
            error_message=COALESCE(NULLIF(?, ''), error_message), completed_at=CASE WHEN ? THEN ? ELSE completed_at END,
            updated_at=? WHERE batch_id=? AND sequence_no=?""",
            (status, alpha_id, child_url, self._json(result) if result is not None else None, error_message,
             terminal, now, now, batch_id, sequence_no),
        )
        # terminal 时回写 alpha_expressions 回测状态 (completed 优先; pruned 不可被覆盖)
        if terminal:
            target = "completed" if status == "completed" else "failed"
            self._get_connection().execute(
                """UPDATE alpha_expressions SET status=?, updated_at=?
                   WHERE expression_sha=(SELECT expression_sha FROM simulation_results
                                         WHERE batch_id=? AND sequence_no=?)
                     AND status NOT IN ('completed', 'pruned')""",
                (target, now, batch_id, sequence_no),
            )
        self._refresh_simulation_batch(batch_id)
        self._get_connection().commit()

    def _refresh_simulation_batch(self, batch_id: int) -> None:
        conn = self._get_connection()
        counts = conn.execute(
            """SELECT COUNT(*) AS total, SUM(status='completed') AS completed,
            SUM(status='failed') AS failed FROM simulation_results WHERE batch_id=?""", (batch_id,)
        ).fetchone()
        completed, failed = int(counts["completed"] or 0), int(counts["failed"] or 0)
        status = "completed" if completed + failed == int(counts["total"] or 0) else "polling"
        now = self._timestamp()
        conn.execute(
            """UPDATE simulation_batches SET status=?, completed_count=?, failed_count=?,
            completed_at=CASE WHEN ?='completed' THEN ? ELSE completed_at END, updated_at=? WHERE id=?""",
            (status, completed, failed, status, now, now, batch_id),
        )

    def mark_expressions_pruned(self, expression_shas: List[str]) -> None:
        """把表达式标记为"被剪枝条"(pruned); 已完成的回测结果保留, 不被覆盖。"""
        now = self._timestamp()
        conn = self._get_connection()
        for sha in expression_shas:
            conn.execute(
                """UPDATE alpha_expressions SET status='pruned', updated_at=?
                   WHERE expression_sha=? AND status != 'completed'""",
                (now, sha),
            )
        conn.commit()

    def get_simulation_batch(self, batch_id: int) -> Optional[Dict[str, Any]]:
        row = self._get_connection().execute("SELECT * FROM simulation_batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None

    def get_simulation_results(self, batch_id: int) -> List[Dict[str, Any]]:
        rows = self._get_connection().execute(
            "SELECT * FROM simulation_results WHERE batch_id=? ORDER BY sequence_no", (batch_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def save_super_candidates(self, candidates: List[Dict[str, Any]], settings: Dict[str, Any]) -> None:
        """Upsert generated Super Alpha hypotheses before any platform submission."""
        now = self._timestamp()
        conn = self._get_connection()
        for candidate in candidates:
            conn.execute(
                """INSERT INTO super_alpha_candidates
                (candidate_sha, component_ids_json, selection_name, selection, combo_name, combo, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_sha) DO UPDATE SET updated_at=excluded.updated_at""",
                (candidate["candidate_sha"], self._json(candidate["component_ids"]), candidate["selection_name"],
                 candidate["selection"], candidate["combo_name"], candidate["combo"], self._json(settings), now, now),
            )
        conn.commit()

    def get_super_candidates(self, status: str | None = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM super_alpha_candidates"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        rows = self._get_connection().execute(sql + " ORDER BY id", params).fetchall()
        candidates = []
        for row in rows:
            value = dict(row)
            value["component_ids"] = json.loads(value.pop("component_ids_json"))
            value.pop("settings_json", None)
            value.pop("id", None)
            value.pop("status", None)
            value.pop("alpha_id", None)
            value.pop("result_json", None)
            value.pop("error_message", None)
            value.pop("created_at", None)
            value.pop("updated_at", None)
            candidates.append(value)
        return candidates

    def mark_super_candidate_result(self, candidate_sha: str, *, alpha_id: str = "", status: str = "completed",
                                    result: Any = None, error_message: str = "") -> None:
        self._get_connection().execute(
            """UPDATE super_alpha_candidates SET status=?, alpha_id=COALESCE(NULLIF(?, ''), alpha_id),
            result_json=COALESCE(?, result_json), error_message=COALESCE(NULLIF(?, ''), error_message), updated_at=?
            WHERE candidate_sha=?""",
            (status, alpha_id, self._json(result) if result is not None else None, error_message, self._timestamp(), candidate_sha),
        )
        self._get_connection().commit()

    # ---------------------------------------------------------------------------
    # 表达式操作
    # ---------------------------------------------------------------------------

    @staticmethod
    def compute_sha(expression: str) -> str:
        """计算表达式SHA256哈希."""
        return hashlib.sha256(expression.encode()).hexdigest()

    @staticmethod
    def compute_alpha_sha(expression: str, settings: Dict[str, Any]) -> str:
        """Hash the normalized expression and complete simulation settings."""
        canonical = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(f"{expression}\n{canonical}".encode("utf-8")).hexdigest()

    def insert_expression(self, expression: str, settings: Dict, *, expression_origin: str = "",
                          batch_id: Optional[int] = None, fields: Optional[List[str]] = None,
                          status: str = "pending", first_operator: Optional[str] = None,
                          commit: bool = True) -> int:
        """插入alpha表达式(去重).

        Args:
            expression: alpha表达式
            settings: 回测设置字典
            expression_origin: 生成来源 (unary_template/first_order/semantic_pair等)
            batch_id: 回测批次id (关联 simulation_batches)
            fields: 表达式用到的字段清单; 缺省时从表达式提取
            status: 回测状态 (pending/completed/failed/pruned)
            first_operator: 第一个操作符; 缺省时从表达式提取

        Returns:
            表达式ID (如果已存在返回已有ID)
        """
        from alpha_operator_framework.domain.operators import extract_first_operator
        from alpha_operator_framework.domain.pruning import extract_fields

        conn = self._get_connection()
        cursor = conn.cursor()

        expression_sha = self.compute_sha(expression)
        settings_json = json.dumps(settings)
        fields_json = self._json(sorted(set(fields if fields is not None else extract_fields(expression))))
        first_operator = first_operator if first_operator is not None else extract_first_operator(expression)
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO alpha_expressions
                    (expression_sha, expression, expression_origin, settings,
                     batch_id, fields, status, first_operator, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (expression_sha, expression, expression_origin, settings_json,
                  batch_id, fields_json, status, first_operator, now, now))
            if commit:
                conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # 已存在: 回填 origin(空才填) + batch_id(取最新) + fields(合并) + first_operator(空才填)
            cursor.execute("""
                UPDATE alpha_expressions
                SET expression_origin = CASE WHEN expression_origin = '' THEN ? ELSE expression_origin END,
                    batch_id = COALESCE(?, batch_id),
                    fields = ?,
                    first_operator = CASE WHEN first_operator = '' THEN ? ELSE first_operator END,
                    updated_at = ?
                WHERE expression_sha = ?
            """, (expression_origin, batch_id, fields_json, first_operator, now, expression_sha))
            if commit:
                conn.commit()
            # 已存在,返回已有ID
            cursor.execute("SELECT id FROM alpha_expressions WHERE expression_sha = ?", (expression_sha,))
            row = cursor.fetchone()
            return row['id'] if row else -1

    def get_expression_by_sha(self, expression_sha: str) -> Optional[AlphaExpression]:
        """通过SHA查询表达式."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM alpha_expressions WHERE expression_sha = ?", (expression_sha,))
        row = cursor.fetchone()

        if row:
            return AlphaExpression(
                id=row['id'],
                expression_sha=row['expression_sha'],
                expression=row['expression'],
                expression_origin=row['expression_origin'],
                settings=row['settings'],
                batch_id=row['batch_id'],
                fields=row['fields'],
                status=row['status'],
                first_operator=row['first_operator'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
        return None

    def catalog_expression(
        self,
        expression: str,
        *,
        stage: str = "first_order",
        family: str = "unary",
        template_index: int = -1,
        fields_per_alpha: int = 0,
        base_fields: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        status: str = "generated",
        expression_origin: str = "",
        batch_id: Optional[int] = None,
        backtest_status: str = "pending",
        commit: bool = True,
    ) -> int:
        """把候选表达式写入现有 alpha_expressions 表，重复表达式幂等处理。

        Args:
            status: settings.status (生成阶段标记, 存 settings JSON)
            batch_id: 回测批次id (新列)
            backtest_status: 回测状态 (新列, pending/completed/failed/pruned)
        """
        settings = {
            "stage": stage,
            "family": family,
            "template_index": template_index,
            "fields_per_alpha": fields_per_alpha,
            "base_fields": base_fields or [],
            "metadata": metadata or {},
            "status": status,
        }
        return self.insert_expression(
            expression, settings,
            expression_origin=expression_origin,
            batch_id=batch_id,
            fields=list(base_fields) if base_fields else None,
            status=backtest_status,
            commit=commit,
        )

    def catalog_tasks(
        self, tasks: List[Any], *, stage: str = "first_order", settings: Optional[Dict] = None,
        batch_id: Optional[int] = None
    ) -> int:
        """批量登记 Task 到现有 alpha_expressions 表.

        性能关键: 逐条 commit 会让 N 条任务产生 N 次 fsync (Windows 上数千条可卡十几分钟)。
        这里把整批放进一个事务, 循环内 commit=False, 最后统一 commit 一次; 异常时回滚。
        """
        if not tasks:
            return 0
        conn = self._get_connection()
        count = 0
        try:
            for task in tasks:
                self.catalog_expression(
                    task.expression,
                    stage=stage,
                    family=task.family,
                    template_index=task.template_index,
                    fields_per_alpha=task.fields_per_alpha,
                    base_fields=list(task.base_fields),
                    metadata=task.meta,
                    expression_origin=task.expression_origin,
                    batch_id=batch_id,
                    commit=False,
                )
                count += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return count

    def sample_catalog_expressions(
        self, expressions: List[str], *, limit: int = 80, seed: Optional[int] = 42,
        distribution: str = "proportional", per_group: int = 0,
        batch_ids: Optional[List[int]] = None,
        base_fields_list: Optional[List[List[str]]] = None,
        max_per_batch: int = 8,
        max_per_batch_glb: int = 4,
        is_glb: bool = False
    ) -> List[str]:
        """分层随机抽样: 批次 → 字段/表达式 → 随机选定.

        抽样策略:
          1. 先按批次(batch_id)分组，保证每个批次有代表性
          2. 批次内按字段组合(base_fields)分组，保证字段多样性
          3. 字段组内按表达式分组(或直接随机)
          4. 最终从每组随机选定，填满 limit

        批次回测上限:
          - 普通地区: 每批最多 max_per_batch (默认8)
          - GLB: 每批最多 max_per_batch_glb (默认4)

        Args:
            expressions: 候选表达式列表
            limit: 抽样上限 (<=0 表示全量)
            seed: 随机种子
            distribution: 批次内分配方式 (proportional/uniform/per_group)
            per_group: distribution="per_group" 时每组抽取数量
            batch_ids: 对应每个表达式的批次ID列表(可选)
            base_fields_list: 对应每个表达式的字段列表(可选)
            max_per_batch: 普通地区每批回测上限
            max_per_batch_glb: GLB每批回测上限
            is_glb: 是否为GLB地区

        Returns:
            抽样后的表达式列表
        """
        import random
        from alpha_operator_framework.domain.operators import extract_first_operator

        if not expressions or limit <= 0:
            return list(expressions)

        rng = random.Random(seed)
        batch_cap = max_per_batch_glb if is_glb else max_per_batch

        # 无批次/字段信息时，退化为按 first_operator 分组
        if not batch_ids and not base_fields_list:
            groups: Dict[str, List[str]] = {}
            for expr in expressions:
                groups.setdefault(extract_first_operator(expr), []).append(expr)
            return self._sample_from_groups(groups, limit, distribution, per_group, rng)

        # 构建索引: expression → (batch_id, base_fields)
        expr_meta: Dict[str, Tuple[Optional[int], Tuple[str, ...]]] = {}
        for i, expr in enumerate(expressions):
            bid = batch_ids[i] if batch_ids and i < len(batch_ids) else None
            fields = tuple(sorted(base_fields_list[i])) if base_fields_list and i < len(base_fields_list) else ()
            expr_meta[expr] = (bid, fields)

        # 第一层: 按批次分组
        by_batch: Dict[Optional[int], List[str]] = {}
        for expr in expressions:
            bid = expr_meta[expr][0]
            by_batch.setdefault(bid, []).append(expr)

        # 每个批次分配的配额 (受 batch_cap 限制)
        n_batches = len(by_batch)
        batch_alloc: Dict[Optional[int], int] = {}
        if distribution == "uniform":
            per_batch = max(1, limit // max(n_batches, 1))
            for bid in by_batch:
                batch_alloc[bid] = min(per_batch, len(by_batch[bid]), batch_cap)
        else:  # proportional
            total = len(expressions)
            for bid, items in by_batch.items():
                batch_alloc[bid] = min((limit * len(items)) // max(total, 1), len(items), batch_cap)

        # 填满 limit (但不超过 batch_cap)
        allocated = sum(batch_alloc.values())
        if allocated < limit:
            remaining = limit - allocated
            for bid in sorted(by_batch, key=lambda b: -len(by_batch.get(b, []))):
                if remaining <= 0:
                    break
                current = batch_alloc.get(bid, 0)
                add = min(remaining, len(by_batch[bid]) - current, batch_cap - current)
                if add > 0:
                    batch_alloc[bid] = current + add
                    remaining -= add

        # 第二层: 批次内按字段组合分组
        out: List[str] = []
        for bid, batch_exprs in by_batch.items():
            batch_limit = batch_alloc.get(bid, 0)
            if batch_limit <= 0:
                continue

            # 按字段组合分组
            by_fields: Dict[Tuple[str, ...], List[str]] = {}
            for expr in batch_exprs:
                fields_key = expr_meta[expr][1]
                by_fields.setdefault(fields_key, []).append(expr)

            # 字段组内分配配额
            n_fields_groups = len(by_fields)
            if n_fields_groups == 0:
                continue

            fields_alloc: Dict[Tuple[str, ...], int] = {}
            if distribution == "uniform":
                per_fg = max(1, batch_limit // max(n_fields_groups, 1))
                for fk in by_fields:
                    fields_alloc[fk] = min(per_fg, len(by_fields[fk]))
            else:
                batch_total = len(batch_exprs)
                for fk, items in by_fields.items():
                    fields_alloc[fk] = min((batch_limit * len(items)) // max(batch_total, 1), len(items))

            # 填满批次配额
            allocated_fg = sum(fields_alloc.values())
            if allocated_fg < batch_limit:
                remaining = batch_limit - allocated_fg
                for fk in sorted(by_fields, key=lambda f: -len(by_fields.get(f, []))):
                    if remaining <= 0:
                        break
                    add = min(remaining, len(by_fields[fk]) - fields_alloc.get(fk, 0))
                    fields_alloc[fk] = fields_alloc.get(fk, 0) + add
                    remaining -= add

            # 第三层: 字段组内随机选取
            for fk in sorted(fields_alloc):
                pool = list(by_fields[fk])
                rng.shuffle(pool)
                out.extend(pool[: fields_alloc[fk]])

        # 未填满时从剩余表达式补齐 (注意不超过 batch_cap)
        if len(out) < limit:
            rest = [e for e in expressions if e not in out]
            rng.shuffle(rest)
            # 按批次计数，确保不超过 batch_cap
            batch_counts: Dict[Optional[int], int] = {}
            for e in out:
                bid = expr_meta[e][0]
                batch_counts[bid] = batch_counts.get(bid, 0) + 1
            for e in rest:
                if len(out) >= limit:
                    break
                bid = expr_meta[e][0]
                if batch_counts.get(bid, 0) < batch_cap:
                    out.append(e)
                    batch_counts[bid] = batch_counts.get(bid, 0) + 1

        return out

    def _sample_from_groups(
        self, groups: Dict[str, List[str]], limit: int,
        distribution: str, per_group: int, rng: random.Random
    ) -> List[str]:
        """从分组中抽样(原逻辑,供无批次信息时使用)."""
        sizes = {op: len(v) for op, v in groups.items()}
        if distribution == "uniform":
            per = max(1, limit // max(len(sizes), 1))
            alloc = {op: min(per, sz) for op, sz in sizes.items()}
        elif distribution == "per_group":
            alloc = {op: min(max(per_group, 0), sz) for op, sz in sizes.items()}
        else:  # proportional
            total = sum(sizes.values())
            alloc = {op: (limit * sz) // total for op, sz in sizes.items()}
            for op in alloc:
                alloc[op] = min(alloc[op], sizes[op])
            remaining = limit - sum(alloc.values())
            for op in sorted(sizes, key=lambda o: (-sizes[o], o)):
                if remaining <= 0:
                    break
                add = min(remaining, sizes[op] - alloc[op])
                alloc[op] += add
                remaining -= add

        out: List[str] = []
        for op in sorted(alloc):
            pool = list(groups[op])
            rng.shuffle(pool)
            out.extend(pool[: alloc[op]])
        if len(out) < limit:
            rest = [e for e in groups.get("__all__", []) if e not in out]
            rng.shuffle(rest)
            out.extend(rest[: limit - len(out)])
        return out

    # ---------------------------------------------------------------------------
    # Alpha详情操作
    # ---------------------------------------------------------------------------

    def insert_alpha_detail(self, detail: AlphaDetail) -> int:
        """插入alpha详情(更新或插入).

        Args:
            detail: AlphaDetail对象

        Returns:
            详情ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        self._upsert_detail(cursor, detail, now)
        conn.commit()
        return cursor.lastrowid

    def update_alpha_status(self, alpha_id: str, status: str) -> None:
        """更新 alpha_details 中的平台状态。"""
        conn = self._get_connection()
        conn.execute(
            "UPDATE alpha_details SET status_platform = ?, updated_at = ? WHERE alpha_id = ?",
            (status, datetime.now().isoformat(), alpha_id),
        )
        conn.commit()

    def update_wf_stage(self, alpha_id: str, wf_stage: str) -> None:
        """更新 alpha_details 中的系统内阶段 (wf_stage). 非法值抛 ValueError."""
        if wf_stage not in WF_STAGES:
            raise ValueError(f"unknown wf_stage: {wf_stage!r} (expected one of {WF_STAGES})")
        conn = self._get_connection()
        conn.execute(
            "UPDATE alpha_details SET wf_stage = ?, updated_at = ? WHERE alpha_id = ?",
            (wf_stage, datetime.now().isoformat(), alpha_id),
        )
        conn.commit()

    def mark_alpha_submitted(self, alpha_id: str) -> None:
        """标记已提交 (wf_stage='submitted'). 供后续 submit_alpha 接线 / 人工调用."""
        self.update_wf_stage(alpha_id, "submitted")

    def mark_alpha_failed(self, alpha_id: str) -> None:
        """标记回测/校验失败 (wf_stage='failed'). 供后续失败校验接线使用."""
        self.update_wf_stage(alpha_id, "failed")

    def _upsert_detail(self, cursor: sqlite3.Cursor, detail: AlphaDetail, now: str) -> None:
        """内部: 插入或更新alpha详情 (upsert, 不提交).

        供 insert_alpha_detail 与 save_result_with_checks 共用,
        保证列清单、VALUES、SET 三处同源,降低列数不匹配风险。
        """
        cursor.execute("""
            INSERT INTO alpha_details (
                alpha_id, expression_sha, alpha_sha, expression,
                region, universe, delay, decay, neutralization, truncation,
                sharpe, fitness, turnover, margin, pnl, returns, drawdown, long_count, short_count,
                grade, stage_platform, status_platform,
                sc_result, sc_value, pc_result, pc_value, checks_json, ra_failed, ppa_failed,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alpha_id) DO UPDATE SET
                expression_sha=excluded.expression_sha,
                alpha_sha=excluded.alpha_sha,
                expression=excluded.expression,
                region=excluded.region,
                universe=excluded.universe,
                delay=excluded.delay,
                decay=excluded.decay,
                neutralization=excluded.neutralization,
                truncation=excluded.truncation,
                sharpe=excluded.sharpe,
                fitness=excluded.fitness,
                turnover=excluded.turnover,
                margin=excluded.margin,
                pnl=excluded.pnl,
                returns=excluded.returns,
                drawdown=excluded.drawdown,
                long_count=excluded.long_count,
                short_count=excluded.short_count,
                grade=excluded.grade,
                stage_platform=excluded.stage_platform,
                status_platform=excluded.status_platform,
                sc_result=excluded.sc_result,
                sc_value=excluded.sc_value,
                pc_result=excluded.pc_result,
                pc_value=excluded.pc_value,
                checks_json=excluded.checks_json,
                ra_failed=excluded.ra_failed,
                ppa_failed=excluded.ppa_failed,
                updated_at=excluded.updated_at
        """, (
            detail.alpha_id, detail.expression_sha, detail.alpha_sha, detail.expression,
            detail.region, detail.universe, detail.delay, detail.decay, detail.neutralization, detail.truncation,
            detail.sharpe, detail.fitness, detail.turnover, detail.margin, detail.pnl, detail.returns, detail.drawdown,
            detail.long_count, detail.short_count,
            detail.grade, detail.stage_platform, detail.status_platform,
            detail.sc_result, detail.sc_value, detail.pc_result, detail.pc_value, detail.checks_json,
            detail.ra_failed, detail.ppa_failed,
            now, now
        ))

    def query_alphas(
        self,
        min_sharpe: Optional[float] = None,
        max_sharpe: Optional[float] = None,
        min_fitness: Optional[float] = None,
        max_fitness: Optional[float] = None,
        region: Optional[str] = None,
        stage_platform: Optional[str] = None,
        status: Optional[str] = None,
        wf_stage: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AlphaDetail]:
        """查询alphas (支持分页).

        Args:
            status: 平台状态 (过滤 status_platform 列, 如 UNSUBMITTED/SUBMITTED)
            stage_platform: 平台阶段 (IS/OS)
            wf_stage: 系统内阶段 (pending_validation/validated/submitted/failed/needs_optimization)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        conditions = []
        params = []

        if min_sharpe is not None:
            conditions.append("sharpe >= ?")
            params.append(min_sharpe)
        if max_sharpe is not None:
            conditions.append("sharpe <= ?")
            params.append(max_sharpe)
        if min_fitness is not None:
            conditions.append("fitness >= ?")
            params.append(min_fitness)
        if max_fitness is not None:
            conditions.append("fitness <= ?")
            params.append(max_fitness)
        if region:
            conditions.append("region = ?")
            params.append(region)
        if stage_platform:
            conditions.append("stage_platform = ?")
            params.append(stage_platform)
        if status:
            conditions.append("status_platform = ?")
            params.append(status)
        if wf_stage:
            conditions.append("wf_stage = ?")
            params.append(wf_stage)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT * FROM alpha_details
            WHERE {where_clause}
            ORDER BY sharpe DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_detail(row) for row in rows]

    def _row_to_detail(self, row: sqlite3.Row) -> AlphaDetail:
        """将数据库行转换为AlphaDetail对象."""
        return AlphaDetail(
            id=row['id'],
            alpha_id=row['alpha_id'],
            expression_sha=row['expression_sha'],
            expression=row['expression'],
            region=row['region'],
            universe=row['universe'],
            delay=row['delay'],
            decay=row['decay'],
            neutralization=row['neutralization'],
            truncation=row['truncation'],
            sharpe=row['sharpe'],
            fitness=row['fitness'],
            turnover=row['turnover'],
            margin=row['margin'],
            pnl=row['pnl'],
            returns=row['returns'],
            drawdown=row['drawdown'],
            long_count=row['long_count'],
            short_count=row['short_count'],
            grade=row['grade'],
            stage_platform=row['stage_platform'],
            status_platform=row['status_platform'],
            wf_stage=row['wf_stage'],
            sc_result=row['sc_result'] or "",
            sc_value=row['sc_value'],
            pc_result=row['pc_result'] or "",
            pc_value=row['pc_value'],
            checks_json=row['checks_json'] or "",
            ra_failed=row['ra_failed'] or 0,
            ppa_failed=row['ppa_failed'] or 0,
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )

    # ---------------------------------------------------------------------------
    # Checks 操作
    # ---------------------------------------------------------------------------

    @staticmethod
    def check_array_to_rows(checks: List[Dict], alpha_id: str = "") -> List[Dict]:
        """把平台 is.checks 数组归一化为 alpha_checks 行 dict.

        除 name/result/limit/value 外的字段(含 year/startDate/endDate/pyramids/
        themes/effective/multiplier/maxCorrelation 及未知字段)序列化进 extra_json。

        Args:
            checks: is.checks 数组
            alpha_id: 当前 alpha_id

        Returns:
            行 dict 列表
        """
        rows = []
        for check in checks or []:
            if not isinstance(check, dict):
                continue
            name = check.get("name") or ""
            if not name:
                continue
            extra = {k: v for k, v in check.items()
                     if k not in ("name", "result", "limit", "value")}
            rows.append({
                "alpha_id": alpha_id,
                "check_name": name,
                "result": check.get("result"),
                "limit": _num(check, "limit"),
                "value": _num(check, "value"),
                "extra_json": json.dumps(extra, ensure_ascii=False) if extra else None,
            })
        return rows

    def _write_checks(self, cursor: sqlite3.Cursor, alpha_id: str, checks: List[Dict], now: str) -> None:
        """内部: 替换式写某 alpha 的 checks (不提交, 由调用方控制事务).

        DELETE + INSERT: 清除已消失的 check, 保证子表与平台返回一致。
        """
        cursor.execute("DELETE FROM alpha_checks WHERE alpha_id = ?", (alpha_id,))
        for row in self.check_array_to_rows(checks, alpha_id):
            cursor.execute("""
                INSERT INTO alpha_checks (alpha_id, check_name, result, "limit", value, extra_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["alpha_id"], row["check_name"], row["result"], row["limit"],
                  row["value"], row["extra_json"], now, now))

    def upsert_checks(self, alpha_id: str, checks: List[Dict]) -> int:
        """替换式写入某 alpha 的全部 checks (独立提交).

        Args:
            alpha_id: 平台alpha_id
            checks: is.checks 数组

        Returns:
            写入的 check 行数
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        self._write_checks(cursor, alpha_id, checks, now)
        conn.commit()
        return len(self.check_array_to_rows(checks, alpha_id))

    def get_checks(self, alpha_id: str) -> List[Dict]:
        """返回某 alpha 的 checks 列表 (extra_json 已合并进条目).

        Args:
            alpha_id: 平台alpha_id

        Returns:
            checks 列表, 每条含 name/result/limit/value 及额外字段
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT check_name, result, "limit", value, extra_json
            FROM alpha_checks
            WHERE alpha_id = ?
            ORDER BY check_name
        """, (alpha_id,))
        rows = cursor.fetchall()

        out = []
        for row in rows:
            item = {
                "name": row["check_name"],
                "result": row["result"],
                "limit": row["limit"],
                "value": row["value"],
            }
            if row["extra_json"]:
                try:
                    extra = json.loads(row["extra_json"])
                    if isinstance(extra, dict):
                        item.update(extra)
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(item)
        return out

    def save_result_with_checks(
        self,
        alpha_id: str,
        is_dict_or_result: Dict,
        settings_dict: Optional[Dict] = None
    ) -> None:
        """保存模拟结果 + 全部 checks 指标 (核心方法).

        兼容两种传入:
          1. 完整结果行: {"alpha_id":..., "regular": {"code":...}, "is": {...}, "settings": {...}}
          2. is 块:      {"sharpe":..., "selfCorrelation":..., "prodCorrelation":..., "checks":[...]}

        PC/SC 提取: is.selfCorrelation/prodCorrelation 标量优先,
        fallback 到 checks 里 SELF_CORRELATION/PROD_CORRELATION 的 value/maxCorrelation。

        单事务写入 alpha_details + alpha_checks, 异常回滚。

        Args:
            alpha_id: 平台alpha_id
            is_dict_or_result: is块或完整结果行
            settings_dict: 回测设置 (可选; 结果行自带 settings 时优先)

        注: 本方法不写 wf_stage; 新行默认 pending_validation, 已存在行保留原阶段。
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # 1. 识别 is 块 / settings / expression
        is_block = is_dict_or_result
        settings = settings_dict or {}
        expression = ""
        top = is_dict_or_result if isinstance(is_dict_or_result, dict) else {}

        if isinstance(is_block, dict) and isinstance(is_block.get("is"), dict):
            # 完整结果行
            is_block = is_block["is"]
            settings = top.get("settings") or settings
            regular = top.get("regular") if isinstance(top.get("regular"), dict) else {}
            expression = regular.get("code") or top.get("expression") or ""
        elif isinstance(is_block, dict):
            expression = is_block.get("expression") or ""

        if not isinstance(is_block, dict):
            is_block = {}

        checks = is_block.get("checks") or []

        # 2. PC/SC 提取
        sc_value, pc_value, sc_result, pc_result = _extract_pc_sc(is_block, checks)

        # 2b. RA/PPA 失败计数 (复用 evaluation.count_failed_gates, 与 WebDataScope failedNumRA/failedNumPPA 一致)
        gate = count_failed_gates(checks)

        # 3. 构造详情
        detail = AlphaDetail(
            alpha_id=alpha_id,
            expression_sha=self.compute_sha(expression) if expression else "",
            alpha_sha=self.compute_alpha_sha(expression, settings) if expression else "",
            expression=expression,
            region=settings.get("region", ""),
            universe=settings.get("universe", ""),
            delay=settings.get("delay", 1),
            decay=settings.get("decay", 0.0),
            neutralization=settings.get("neutralization", ""),
            truncation=settings.get("truncation", 0.0),
            sharpe=_num(is_block, "sharpe") or 0.0,
            fitness=_num(is_block, "fitness") or 0.0,
            turnover=_num(is_block, "turnover") or 0.0,
            margin=_num(is_block, "margin") or 0.0,
            pnl=_num(is_block, "pnl") or 0.0,
            returns=_num(is_block, "returns") or 0.0,
            drawdown=_num(is_block, "drawdown") or 0.0,
            long_count=int(_num(is_block, "longCount") or 0),
            short_count=int(_num(is_block, "shortCount") or 0),
            grade=is_block.get("grade") or top.get("grade") or "",
            stage_platform=settings.get("stage") or top.get("stage") or "",
            status_platform=settings.get("status") or top.get("status") or "",
            sc_result=sc_result,
            sc_value=sc_value,
            pc_result=pc_result,
            pc_value=pc_value,
            checks_json=json.dumps(checks, ensure_ascii=False) if checks else None,
            ra_failed=gate.failed_ra,
            ppa_failed=gate.failed_ppa,
        )

        # 4. 单事务写入
        try:
            self._upsert_detail(cursor, detail, now)
            self._write_checks(cursor, alpha_id, checks, now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ---------------------------------------------------------------------------
    # 批量导入
    # ---------------------------------------------------------------------------

    def import_from_csv(self, csv_path: str) -> int:
        """从CSV导入模拟结果.

        Args:
            csv_path: CSV文件路径

        Returns:
            导入数量
        """
        import pandas as pd

        df = pd.read_csv(csv_path)
        count = 0

        for _, row in df.iterrows():
            try:
                # 解析settings
                settings = eval(row['settings']) if isinstance(row['settings'], str) else {}
                regular = eval(row['regular']) if isinstance(row['regular'], str) else {}
                is_result = eval(row['is']) if isinstance(row['is'], str) else {}

                expression = regular.get('code', '')

                # 插入表达式
                self.insert_expression(expression, settings)

                # PC/SC + checks
                checks = is_result.get('checks') or []
                sc_value, pc_value, sc_result, pc_result = _extract_pc_sc(is_result, checks)
                gate = count_failed_gates(checks)

                # 构建详情
                detail = AlphaDetail(
                    alpha_id=row['alpha_id'],
                    expression_sha=self.compute_sha(expression),
                    expression=expression,
                    region=settings.get('region', ''),
                    universe=settings.get('universe', ''),
                    delay=settings.get('delay', 1),
                    decay=settings.get('decay', 0.0),
                    neutralization=settings.get('neutralization', ''),
                    truncation=settings.get('truncation', 0.0),
                    sharpe=is_result.get('sharpe', 0.0),
                    fitness=is_result.get('fitness', 0.0),
                    turnover=is_result.get('turnover', 0.0),
                    margin=is_result.get('margin', 0.0),
                    pnl=is_result.get('pnl', 0.0),
                    returns=is_result.get('returns', 0.0),
                    drawdown=is_result.get('drawdown', 0.0),
                    long_count=is_result.get('longCount', 0),
                    short_count=is_result.get('shortCount', 0),
                    grade=row.get('grade', ''),
                    stage_platform=row.get('stage', ''),
                    status_platform=row.get('status', ''),
                    sc_result=sc_result,
                    sc_value=sc_value,
                    pc_result=pc_result,
                    pc_value=pc_value,
                    checks_json=json.dumps(checks, ensure_ascii=False) if checks else None,
                    ra_failed=gate.failed_ra,
                    ppa_failed=gate.failed_ppa,
                )

                self.insert_alpha_detail(detail)

                # 有 checks 时写子表
                if checks:
                    self.upsert_checks(row['alpha_id'], checks)

                count += 1

            except Exception as e:
                print(f"导入失败 {row.get('alpha_id', 'unknown')}: {e}")

        return count

    def close(self):
        """关闭数据库连接."""
        if self.conn:
            self.conn.close()
            self.conn = None

    # ---------------------------------------------------------------------------
    # Datafields 操作 (有信号的数据字段表)
    # ---------------------------------------------------------------------------

    def upsert_datafield(self, row: Dict[str, Any], *, expression_shas: Optional[List[str]] = None) -> Optional[str]:
        """把平台原始 datafield 行 upsert 进 datafields 表.

        同一 (field_id, dataset_id, region, delay) 的行合并 universes 与 expression_shas。

        Args:
            row: fetch_datafields 返回的原始行 (含 id/dataset{id,name}/region/delay/universe/
                 type/coverage/userCount/alphaCount)
            expression_shas: 使用该字段的 alpha 表达式 sha (合并累加)

        Returns:
            field_id; 缺 id 返回 None
        """
        field_id = str(row.get("id") or "")
        if not field_id:
            return None
        dataset = row.get("dataset") or {}
        dataset_id = str(dataset.get("id") or row.get("dataset_id") or "")
        dataset_name = str(dataset.get("name") or "")
        region = str(row.get("region") or "")
        delay = int(row.get("delay") or 1)
        universe = str(row.get("universe") or "")
        # 平台 category: 兼容嵌套 dict {id,...} 与字符串
        cat = row.get("category") or ""
        category = str(cat.get("id") or "") if isinstance(cat, dict) else str(cat or "")
        now = self._timestamp()
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT universes_json, expression_shas_json FROM datafields "
            "WHERE field_id=? AND dataset_id=? AND region=? AND delay=?",
            (field_id, dataset_id, region, delay),
        ).fetchone()
        universes = set(json.loads(existing["universes_json"])) if existing else set()
        if universe:
            universes.add(universe)
        shas = set(json.loads(existing["expression_shas_json"])) if existing else set()
        shas.update(expression_shas or [])
        conn.execute("""
            INSERT INTO datafields (field_id, dataset_id, dataset_name, description, type, region, delay,
                universes_json, coverage, user_count, alpha_count, category, expression_shas_json,
                last_fetched_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(field_id, dataset_id, region, delay) DO UPDATE SET
                dataset_name=excluded.dataset_name,
                description=excluded.description,
                type=excluded.type,
                universes_json=excluded.universes_json,
                coverage=excluded.coverage,
                user_count=excluded.user_count,
                alpha_count=excluded.alpha_count,
                category=excluded.category,
                expression_shas_json=excluded.expression_shas_json,
                last_fetched_at=excluded.last_fetched_at,
                updated_at=excluded.updated_at
        """, (
            field_id, dataset_id, dataset_name, str(row.get("description") or ""),
            str(row.get("type") or "MATRIX").upper(), region, delay,
            self._json(sorted(universes)), _num(row, "coverage") or 0.0,
            int(_num(row, "userCount") or 0), int(_num(row, "alphaCount") or 0),
            category, self._json(sorted(shas)), now, now, now,
        ))
        conn.commit()
        return field_id

    def upsert_datafields(self, rows: List[Dict[str, Any]], *,
                          expression_shas: Optional[List[str]] = None) -> int:
        """批量 upsert datafield 行."""
        count = 0
        for row in rows or []:
            if self.upsert_datafield(row, expression_shas=expression_shas):
                count += 1
        return count

    def upsert_field_signal_stats(self, rows: List[Dict[str, Any]], *,
                                  accumulate: bool = False) -> int:
        """批量 upsert 字段级信号统计行 (研究闭环 P0 沉淀, 第6步回流第1步).

        Args:
            rows: 每行含 field_id/dataset_id/region/universe/delay/round 及
                  trials/signal_count/hit_rate/avg_sharpe/max_sharpe/min_sharpe/avg_fitness
            accumulate: True 时累加到已有值 (trials/signal_count 相加, max_sharpe 取更大,
                  min_sharpe 取更小, hit_rate 重算), 供多轮累积沉淀; 默认覆盖

        Returns:
            写入行数
        """
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for row in rows or []:
            field_id = str(row.get("field_id") or "")
            if not field_id:
                continue
            key = (
                field_id, str(row.get("dataset_id") or ""), str(row.get("region") or ""),
                str(row.get("universe") or ""), int(row.get("delay") or 1),
                int(row.get("round") or 0),
            )
            trials = int(row.get("trials") or 0)
            signal_count = int(row.get("signal_count") or 0)
            hit_rate = _num(row, "hit_rate") or 0.0
            avg_sharpe = _num(row, "avg_sharpe") or 0.0
            max_sharpe = _num(row, "max_sharpe") or 0.0
            min_sharpe = _num(row, "min_sharpe") or 0.0
            avg_fitness = _num(row, "avg_fitness") or 0.0

            if accumulate:
                # 多轮累积沉淀的语义: 不同字段累加规则不同, 需分开处理:
                #   - trials / signal_count 是「计数」→ 直接相加 (扩大样本量)
                #   - max_sharpe / min_sharpe 是「极值」→ 取更大 / 更小 (保持极值语义)
                #   - hit_rate 是「派生量」→ 由累加后的 trials/signal_count 重算,
                #     不能把两轮的 hit_rate 直接相加 (会失去分母信息)
                #   - avg_sharpe / avg_fitness 是「均值」→ 此处简单覆盖 (上一轮的均值),
                #     精确累积需额外保存 sum/count, 当前权衡下不做
                existing = conn.execute(
                    "SELECT trials, signal_count, max_sharpe, min_sharpe FROM field_signal_stats "
                    "WHERE field_id=? AND dataset_id=? AND region=? AND universe=? AND delay=? AND round=?",
                    key,
                ).fetchone()
                if existing:
                    trials += int(existing["trials"] or 0)
                    signal_count += int(existing["signal_count"] or 0)
                    max_sharpe = max(max_sharpe, float(existing["max_sharpe"] or 0.0))
                    min_sharpe = min(min_sharpe, float(existing["min_sharpe"] or 0.0))
                hit_rate = (signal_count / trials) if trials else 0.0

            conn.execute("""
                INSERT INTO field_signal_stats (field_id, dataset_id, region, universe, delay, round,
                    trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe, avg_fitness,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(field_id, dataset_id, region, universe, delay, round) DO UPDATE SET
                    trials=excluded.trials,
                    signal_count=excluded.signal_count,
                    hit_rate=excluded.hit_rate,
                    avg_sharpe=excluded.avg_sharpe,
                    max_sharpe=excluded.max_sharpe,
                    min_sharpe=excluded.min_sharpe,
                    avg_fitness=excluded.avg_fitness,
                    updated_at=excluded.updated_at
            """, (
                field_id, key[1], key[2], key[3], key[4], key[5],
                trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe, avg_fitness,
                now, now,
            ))
            count += 1
        conn.commit()
        return count

    def get_field_signal_stats(self, *, region: Optional[str] = None,
                               universe: Optional[str] = None,
                               delay: Optional[int] = None,
                               round_n: Optional[int] = None,
                               min_trials: int = 1,
                               limit: int = 200) -> List[Dict[str, Any]]:
        """查询字段级信号统计, 按 hit_rate 降序 (下一轮加权采样候选).

        Args:
            region: 区域过滤 (可选)
            universe: 股票池过滤 (可选)
            delay: 延迟过滤 (可选)
            round_n: 轮次过滤 (可选)
            min_trials: 最小回测次数 (过滤噪声)
            limit: 返回上限
        """
        sql = "SELECT * FROM field_signal_stats"
        conds = ["trials >= ?"]
        params: List[Any] = [min_trials]
        if region:
            conds.append("region = ?")
            params.append(region)
        if universe:
            conds.append("universe = ?")
            params.append(universe)
        if delay is not None:
            conds.append("delay = ?")
            params.append(int(delay))
        if round_n is not None:
            conds.append("round = ?")
            params.append(int(round_n))
        sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY hit_rate DESC, signal_count DESC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def upsert_pair_signal_stats(self, rows: List[Dict[str, Any]], *,
                                 accumulate: bool = True) -> int:
        """批量 upsert 配对级信号统计行 (研究闭环 P2 沉淀).

        Args:
            rows: 每行含 pair_spec/pair_kind/region/universe/delay/round 及
                  trials/signal_count/hit_rate/avg_sharpe/max_sharpe/min_sharpe
            accumulate: 累加语义同 upsert_field_signal_stats (计数相加, 极值取更大/更小,
                  hit_rate 重算); 配对沉淀默认累积

        Returns:
            写入行数
        """
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for row in rows or []:
            pair_spec = str(row.get("pair_spec") or "")
            if not pair_spec:
                continue
            key = (
                pair_spec, str(row.get("region") or ""), str(row.get("universe") or ""),
                int(row.get("delay") or 1), int(row.get("round") or 0),
            )
            trials = int(row.get("trials") or 0)
            signal_count = int(row.get("signal_count") or 0)
            hit_rate = _num(row, "hit_rate") or 0.0
            avg_sharpe = _num(row, "avg_sharpe") or 0.0
            max_sharpe = _num(row, "max_sharpe") or 0.0
            min_sharpe = _num(row, "min_sharpe") or 0.0

            if accumulate:
                existing = conn.execute(
                    "SELECT trials, signal_count, max_sharpe, min_sharpe FROM pair_signal_stats "
                    "WHERE pair_spec=? AND region=? AND universe=? AND delay=? AND round=?",
                    key,
                ).fetchone()
                if existing:
                    trials += int(existing["trials"] or 0)
                    signal_count += int(existing["signal_count"] or 0)
                    max_sharpe = max(max_sharpe, float(existing["max_sharpe"] or 0.0))
                    min_sharpe = min(min_sharpe, float(existing["min_sharpe"] or 0.0))
                hit_rate = (signal_count / trials) if trials else 0.0

            conn.execute("""
                INSERT INTO pair_signal_stats (pair_spec, pair_kind, region, universe, delay, round,
                    trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pair_spec, region, universe, delay, round) DO UPDATE SET
                    trials=excluded.trials,
                    signal_count=excluded.signal_count,
                    hit_rate=excluded.hit_rate,
                    avg_sharpe=excluded.avg_sharpe,
                    max_sharpe=excluded.max_sharpe,
                    min_sharpe=excluded.min_sharpe,
                    updated_at=excluded.updated_at
            """, (
                pair_spec, str(row.get("pair_kind") or ""), key[1], key[2], key[3], key[4],
                trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe,
                now, now,
            ))
            count += 1
        conn.commit()
        return count

    def get_pair_signal_stats(self, *, region: Optional[str] = None,
                              round_n: Optional[int] = None,
                              min_trials: int = 1,
                              limit: int = 200) -> List[Dict[str, Any]]:
        """查询配对级信号统计, 按 hit_rate 降序 (下一轮优先复用有信号的配对)."""
        sql = "SELECT * FROM pair_signal_stats"
        conds = ["trials >= ?"]
        params: List[Any] = [min_trials]
        if region:
            conds.append("region = ?")
            params.append(region)
        if round_n is not None:
            conds.append("round = ?")
            params.append(int(round_n))
        sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY hit_rate DESC, signal_count DESC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_datafields(self, *, region: Optional[str] = None, dataset_id: str = "",
                       limit: int = 200) -> List[DataField]:
        """查询 datafields 表 (支持 region/dataset_id 过滤)."""
        sql = "SELECT * FROM datafields"
        params: List[Any] = []
        conds = []
        if region:
            conds.append("region = ?")
            params.append(region)
        if dataset_id:
            conds.append("dataset_id = ?")
            params.append(dataset_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY field_id LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        out: List[DataField] = []
        for r in rows:
            out.append(DataField(
                field_id=r["field_id"], dataset_id=r["dataset_id"], dataset_name=r["dataset_name"],
                description=r["description"], type=r["type"], region=r["region"], delay=r["delay"],
                universes=json.loads(r["universes_json"] or "[]"), coverage=r["coverage"],
                user_count=r["user_count"], alpha_count=r["alpha_count"], category=r["category"] or "",
                expression_shas=json.loads(r["expression_shas_json"] or "[]"),
                last_fetched_at=r["last_fetched_at"], created_at=r["created_at"], updated_at=r["updated_at"],
            ))
        return out

    def missing_datafield_candidates(self, *, region: Optional[str] = None,
                                     delay: Optional[int] = None, limit: int = 200) -> List[str]:
        """返回已被 alpha 使用、但 datafields 表中缺失的字段id池 (增量采集候选).

        Args:
            region: 过滤已采集字段的 region (可选)
            delay: 过滤已采集字段的 delay (可选)
            limit: 返回上限
        """
        rows = self._get_connection().execute(
            "SELECT fields FROM alpha_expressions WHERE fields IS NOT NULL AND fields != '[]'"
        ).fetchall()
        used: set[str] = set()
        for r in rows:
            try:
                used.update(json.loads(r["fields"]))
            except (json.JSONDecodeError, TypeError):
                pass
        if region is not None and delay is not None:
            have = {r["field_id"] for r in self._get_connection().execute(
                "SELECT DISTINCT field_id FROM datafields WHERE region=? AND delay=?", (region, delay))}
        else:
            have = {r["field_id"] for r in self._get_connection().execute(
                "SELECT DISTINCT field_id FROM datafields")}
        return sorted(used - have)[:limit]

    # ---------------------------------------------------------------------------
    # Template 类库操作
    # ---------------------------------------------------------------------------

    def upsert_templates(self, templates: Sequence[Template], *, overwrite: bool = False) -> int:
        """批量 upsert template_library.

        overwrite=False 时 ON CONFLICT(name) DO NOTHING (保留用户编辑, 只填缺失);
        overwrite=True 时 DO UPDATE 全字段。
        """
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for tpl in templates:
            conflict = "DO UPDATE SET " + ", ".join(
                f"{c}=excluded.{c}" for c in (
                    "title", "family", "template_type", "expression_template", "template_index",
                    "fields_per_alpha", "expression_origin", "field_types_json", "categories_json",
                    "dataset_families_json", "placeholders_json", "group_slots_json", "slot_count",
                    "description", "rationale", "example_expression", "settings_hint_json",
                    "field_candidates_json", "operators_used_json", "source_json", "updated_at"))
            if not overwrite:
                conflict = "DO NOTHING"
            cursor = conn.execute(f"""
                INSERT INTO template_library (
                    name, title, family, template_type, expression_template, template_index,
                    fields_per_alpha, expression_origin, field_types_json, categories_json,
                    dataset_families_json, placeholders_json, group_slots_json, slot_count,
                    description, rationale, example_expression, settings_hint_json,
                    field_candidates_json, operators_used_json, source_json, active,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) {conflict}
            """, (
                tpl.name, tpl.title, tpl.family, tpl.template_type, tpl.expression_template,
                tpl.template_index, tpl.fields_per_alpha, tpl.expression_origin,
                self._json(tpl.field_types), self._json(tpl.categories), self._json(tpl.dataset_families),
                self._json(tpl.placeholders), self._json(tpl.group_slots), tpl.slot_count,
                tpl.description, tpl.rationale, tpl.example_expression, self._json(tpl.settings_hint),
                self._json(tpl.field_candidates), self._json(tpl.operators_used), self._json(tpl.source),
                tpl.active, now, now))
            count += 1
        conn.commit()
        return count

    @staticmethod
    def _row_to_template(row: sqlite3.Row) -> Template:
        return Template(
            id=row["id"], name=row["name"], title=row["title"], family=row["family"],
            template_type=row["template_type"], expression_template=row["expression_template"],
            template_index=row["template_index"], fields_per_alpha=row["fields_per_alpha"],
            expression_origin=row["expression_origin"],
            field_types=json.loads(row["field_types_json"] or "[]"),
            categories=json.loads(row["categories_json"] or "[]"),
            dataset_families=json.loads(row["dataset_families_json"] or "[]"),
            placeholders=json.loads(row["placeholders_json"] or "{}"),
            group_slots=json.loads(row["group_slots_json"] or "[]"),
            slot_count=row["slot_count"], description=row["description"], rationale=row["rationale"],
            example_expression=row["example_expression"],
            settings_hint=json.loads(row["settings_hint_json"] or "{}"),
            field_candidates=json.loads(row["field_candidates_json"] or "{}"),
            operators_used=json.loads(row["operators_used_json"] or "[]"),
            source=json.loads(row["source_json"] or "{}"),
            active=row["active"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_templates(self, *, active_only: bool = True,
                       families: Optional[Sequence[str]] = None,
                       categories: Optional[Sequence[str]] = None,
                       template_type: Optional[str] = None,
                       names: Optional[Sequence[str]] = None) -> List[Template]:
        """查询模板库.

        Args:
            active_only: 只返回 active=1
            families: 按 family 过滤 (如 ("unary", "binary"))
            categories: 按 category 过滤; 语义=返回 categories 为空(=ALL)或与入参有交集的模板
            template_type: placeholder/fixed 过滤
            names: 按 name 过滤
        """
        sql = "SELECT * FROM template_library WHERE 1=1"
        params: List[Any] = []
        if active_only:
            sql += " AND active=1"
        if families:
            sql += " AND family IN ({})".format(",".join("?" * len(families)))
            params.extend(families)
        if template_type:
            sql += " AND template_type=?"
            params.append(template_type)
        if names:
            sql += " AND name IN ({})".format(",".join("?" * len(names)))
            params.extend(names)
        rows = self._get_connection().execute(sql + " ORDER BY family, template_index, name", params).fetchall()
        out = [self._row_to_template(r) for r in rows]
        if categories:
            want = set(categories)
            out = [t for t in out if not t.categories or (want & set(t.categories))]
        return out

    def seed_template_library(self, *, force: bool = False,
                              include_knowledge_base: bool = False,
                              knowledge_base_dir: Optional[str | Path] = None) -> int:
        """幂等写入 4 族模板种子 (可选含知识库模板)."""
        from alpha_operator_framework.generation.template_library import seed_template_library as _seed
        return _seed(self, force=force, include_knowledge_base=include_knowledge_base,
                     knowledge_base_dir=knowledge_base_dir)


__all__ = [
    "AlphaDatabase",
    "AlphaExpression",
    "AlphaDetail",
    "DataField",
    "Template",
    "persist_workflow_row",
]
