"""Alpha repository check persistence operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..base import BaseRepository, _extract_pc_sc, _num
from ..models import AlphaDetail
from alpha_operator_framework.domain.evaluation import count_failed_gates


class AlphaChecksMixin(BaseRepository):
    """Check normalization, reads, writes, and atomic result persistence."""

    @staticmethod
    def check_array_to_rows(checks: List[Dict], alpha_id: str = "") -> List[Dict]:
        """将 is.checks 数组归一化为 alpha_checks 行 dict."""
        rows = []
        for check in checks or []:
            if not isinstance(check, dict):
                continue
            name = check.get("name") or ""
            if not name:
                continue
            extra = {k: v for k, v in check.items() if k not in ("name", "result", "limit", "value")}
            rows.append({
                "alpha_id": alpha_id,
                "check_name": name,
                "result": check.get("result"),
                "limit": _num(check, "limit"),
                "value": _num(check, "value"),
                "extra_json": json.dumps(extra, ensure_ascii=False) if extra else None,
            })
        return rows

    def _write_checks(self, cursor: Any, alpha_id: str, checks: List[Dict], now: str) -> None:
        """内部: 替换式写入 checks."""
        cursor.execute("DELETE FROM alpha_checks WHERE alpha_id = ?", (alpha_id,))
        for row in self.check_array_to_rows(checks, alpha_id):
            cursor.execute("""
                INSERT INTO alpha_checks (alpha_id, check_name, result, "limit", value, extra_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["alpha_id"], row["check_name"], row["result"], row["limit"],
                  row["value"], row["extra_json"], now, now))

    def upsert_checks(self, alpha_id: str, checks: List[Dict]) -> int:
        """替换式写入某 alpha 的全部 checks."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        self._write_checks(cursor, alpha_id, checks, now)
        conn.commit()
        return len(self.check_array_to_rows(checks, alpha_id))

    def get_checks(self, alpha_id: str) -> List[Dict]:
        """返回某 alpha 的 checks 列表."""
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

    def get_alpha_checks(self, alpha_id: str) -> List[Any]:
        """返回某 alpha 的 checks 详细模型列表."""
        from ..models import AlphaCheck
        conn = self._get_connection()
        rows = conn.execute(
            """SELECT check_name, result, "limit", value, extra_json FROM alpha_checks
               WHERE alpha_id = ? ORDER BY check_name""",
            (alpha_id,),
        ).fetchall()
        return [
            AlphaCheck(
                check_name=r["check_name"],
                result=r["result"],
                limit=r["limit"],
                value=r["value"],
                extra_json=r["extra_json"],
            )
            for r in rows
        ]

    def save_result_with_checks(
        self,
        alpha_id: str,
        is_dict_or_result: Dict,
        settings_dict: Optional[Dict] = None
    ) -> None:
        """保存模拟结果 + 全部 checks 指标."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        is_block = is_dict_or_result
        settings = settings_dict or {}
        expression = ""
        top = is_dict_or_result if isinstance(is_dict_or_result, dict) else {}

        if isinstance(is_block, dict) and isinstance(is_block.get("is"), dict):
            is_block = is_block["is"]
            settings = top.get("settings") or settings
            regular = top.get("regular") if isinstance(top.get("regular"), dict) else {}
            expression = regular.get("code") or top.get("expression") or ""
        elif isinstance(is_block, dict):
            expression = is_block.get("expression") or ""

        if not isinstance(is_block, dict):
            is_block = {}

        checks = is_block.get("checks") or []
        sc_value, pc_value, sc_result, pc_result = _extract_pc_sc(is_block, checks)
        gate = count_failed_gates(checks)

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

        try:
            self._upsert_detail(cursor, detail, now)
            self._write_checks(cursor, alpha_id, checks, now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

