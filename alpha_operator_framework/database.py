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
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class AlphaExpression:
    """Alpha表达式."""
    id: Optional[int] = None
    expression_sha: str = ""  # SHA256哈希
    expression: str = ""      # alpha表达式
    settings: str = ""        # JSON字符串
    created_at: str = ""      # ISO格式时间
    updated_at: str = ""


@dataclass
class AlphaDetail:
    """Alpha详情(平铺所有字段)."""
    id: Optional[int] = None
    alpha_id: str = ""
    expression_sha: str = ""
    expression: str = ""

    # 回测设置
    region: str = ""
    universe: str = ""
    delay: int = 1
    decay: float = 0.0
    neutralization: str = ""
    truncation: float = 0.0

    # 回测指标
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0
    pnl: float = 0.0
    returns: float = 0.0
    drawdown: float = 0.0
    long_count: int = 0
    short_count: int = 0

    # 平台信息
    grade: str = ""           # INFERIOR/AVERAGE
    stage_platform: str = ""   # IS/OS
    status_platform: str = ""  # UNSUBMITTED

    # 提交检查指标
    sc_result: str = ""                 # SELF_CORRELATION: PASS/FAIL/WARNING/ERROR/PENDING
    sc_value: Optional[float] = None    # self-correlation max(标量)
    pc_result: str = ""                 # PROD_CORRELATION
    pc_value: Optional[float] = None    # prod-correlation max(标量)
    checks_json: str = ""               # 完整 is.checks 数组原样 JSON

    # 时间戳
    created_at: str = ""
    updated_at: str = ""


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
        stage: 阶段 (survey/deepen/submit)
        status: 状态 (pending/kept/rejected/ready/optimize)

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

    def __init__(self, db_path: str = "alpha_research.db"):
        """初始化数据库.

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.conn = None
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn

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
            settings TEXT NOT NULL,
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

            -- 提交检查指标
            sc_result TEXT,
            sc_value REAL,
            pc_result TEXT,
            pc_value REAL,
            checks_json TEXT,

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
        existing = {r["name"] for r in cursor.execute("PRAGMA table_info(alpha_details)")}
        for col, decl in (("sc_result", "TEXT"), ("sc_value", "REAL"),
                          ("pc_result", "TEXT"), ("pc_value", "REAL"), ("checks_json", "TEXT")):
            if col not in existing:
                cursor.execute(f"ALTER TABLE alpha_details ADD COLUMN {col} {decl}")

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expr_sha ON alpha_expressions(expression_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_sha ON alpha_details(expression_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_sharpe ON alpha_details(sharpe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_fitness ON alpha_details(fitness)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detail_stage ON alpha_details(stage_platform)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checks_alpha ON alpha_checks(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checks_name ON alpha_checks(check_name)")

        # 新表索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_queue_alpha ON alpha_optimization_queue(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_queue_status ON alpha_optimization_queue(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_queue_priority ON alpha_optimization_queue(priority)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_cand_alpha ON alpha_submission_candidates(alpha_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_cand_submitted ON alpha_submission_candidates(is_submitted)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_cand_sharpe ON alpha_submission_candidates(sharpe)")

        conn.commit()

    # ---------------------------------------------------------------------------
    # 表达式操作
    # ---------------------------------------------------------------------------

    @staticmethod
    def compute_sha(expression: str) -> str:
        """计算表达式SHA256哈希."""
        return hashlib.sha256(expression.encode()).hexdigest()

    def insert_expression(self, expression: str, settings: Dict) -> int:
        """插入alpha表达式(去重).

        Args:
            expression: alpha表达式
            settings: 回测设置字典

        Returns:
            表达式ID (如果已存在返回已有ID)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        expression_sha = self.compute_sha(expression)
        settings_json = json.dumps(settings)
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO alpha_expressions (expression_sha, expression, settings, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (expression_sha, expression, settings_json, now, now))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
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
                settings=row['settings'],
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
    ) -> int:
        """把候选表达式写入现有 alpha_expressions 表，重复表达式幂等处理。"""
        settings = {
            "stage": stage,
            "family": family,
            "template_index": template_index,
            "fields_per_alpha": fields_per_alpha,
            "base_fields": base_fields or [],
            "metadata": metadata or {},
            "status": status,
        }
        return self.insert_expression(expression, settings)

    def catalog_tasks(
        self, tasks: List[Any], *, stage: str = "first_order", settings: Optional[Dict] = None
    ) -> int:
        """批量登记 Task 到现有 alpha_expressions 表。"""
        count = 0
        for task in tasks:
            self.catalog_expression(
                task.expression,
                stage=stage,
                family=task.family,
                template_index=task.template_index,
                fields_per_alpha=task.fields_per_alpha,
                base_fields=list(task.base_fields),
                metadata=task.meta,
            )
            count += 1
        return count

    def sample_catalog_expressions(
        self, expressions: List[str], *, limit: int = 80, seed: Optional[int] = 42
    ) -> List[str]:
        """从本次已写入 alpha_expressions 的表达式中随机抽样。"""
        import random
        selected = list(expressions)
        random.Random(seed).shuffle(selected)
        return selected if limit <= 0 else selected[:limit]

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

    def _upsert_detail(self, cursor: sqlite3.Cursor, detail: AlphaDetail, now: str) -> None:
        """内部: 插入或更新alpha详情 (upsert, 不提交).

        供 insert_alpha_detail 与 save_result_with_checks 共用,
        保证列清单、VALUES、SET 三处同源,降低列数不匹配风险。
        """
        cursor.execute("""
            INSERT INTO alpha_details (
                alpha_id, expression_sha, expression,
                region, universe, delay, decay, neutralization, truncation,
                sharpe, fitness, turnover, margin, pnl, returns, drawdown, long_count, short_count,
                grade, stage_platform, status_platform,
                sc_result, sc_value, pc_result, pc_value, checks_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alpha_id) DO UPDATE SET
                expression_sha=excluded.expression_sha,
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
                updated_at=excluded.updated_at
        """, (
            detail.alpha_id, detail.expression_sha, detail.expression,
            detail.region, detail.universe, detail.delay, detail.decay, detail.neutralization, detail.truncation,
            detail.sharpe, detail.fitness, detail.turnover, detail.margin, detail.pnl, detail.returns, detail.drawdown,
            detail.long_count, detail.short_count,
            detail.grade, detail.stage_platform, detail.status_platform,
            detail.sc_result, detail.sc_value, detail.pc_result, detail.pc_value, detail.checks_json,
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
        limit: int = 100,
        offset: int = 0
    ) -> List[AlphaDetail]:
        """查询alphas (支持分页)."""
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
            conditions.append("status = ?")
            params.append(status)

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
            sc_result=row['sc_result'] or "",
            sc_value=row['sc_value'],
            pc_result=row['pc_result'] or "",
            pc_value=row['pc_value'],
            checks_json=row['checks_json'] or "",
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

        # 3. 构造详情
        detail = AlphaDetail(
            alpha_id=alpha_id,
            expression_sha=self.compute_sha(expression) if expression else "",
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
                    checks_json=json.dumps(checks, ensure_ascii=False) if checks else None
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


__all__ = [
    "AlphaDatabase",
    "AlphaExpression",
    "AlphaDetail",
    "persist_workflow_row",
]
