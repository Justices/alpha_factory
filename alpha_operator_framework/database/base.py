"""Alpha 仓储基础设施基类 (Base Repository).

提供统一的连接管理、事务控制与序列化工具函数。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .config import get_database_path, DEFAULT_SQLITE_PATH
from .connection import DatabaseConnectionManager


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


_AGG_OPS_RE = re.compile(r"vec_(?:avg|sum|min|max|count|stddev|range)")


def _isomorphic_fingerprint(expr: str) -> str:
    """同构指纹: 把聚合算子(vec_avg/sum/min/max/count/stddev/range)归一化为 vec_AGG."""
    return _AGG_OPS_RE.sub("vec_AGG", expr)


class BaseRepository:
    """仓储基础基类，封装底层连接池与通用事务辅助工具."""

    DEFAULT_DB_PATH = DEFAULT_SQLITE_PATH

    def __init__(
        self,
        db_path: Optional[Union[str, Path, DatabaseConnectionManager]] = None,
        timeout: float = 30.0,
        wal_mode: bool = True,
    ):
        if isinstance(db_path, DatabaseConnectionManager):
            self.manager = db_path
            self.db_path = getattr(self.manager, "db_path", get_database_path(None))
        else:
            self.db_path = get_database_path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.manager = DatabaseConnectionManager(self.db_path, timeout=timeout, wal_mode=wal_mode)

    @property
    def conn(self) -> sqlite3.Connection:
        """保持向后兼容的当前线程连接访问."""
        return self.manager.get_connection()

    @conn.setter
    def conn(self, value: Any) -> None:
        pass

    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程数据库连接."""
        return self.manager.get_connection()

    def transaction(self):
        """获取当前线程的事务上下文 (自动 COMMIT / ROLLBACK)."""
        return self.manager.transaction()

    def close(self) -> None:
        """显式关闭底层连接 (释放文件句柄)."""
        self.manager.close_all()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
