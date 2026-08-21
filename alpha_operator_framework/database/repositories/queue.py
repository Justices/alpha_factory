"""任务队列、提交候选与组合池仓储 (Optimization Queue & Candidates Repository).

管理表:
  - alpha_optimization_queue (待优化因子优先队列)
  - alpha_submission_candidates (达标因子提交候选池)
  - super_alpha_candidates (Super Alpha 组合假设池)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..base import BaseRepository


class QueueRepository(BaseRepository):
    """任务队列、提交候选与组合池仓储."""

    def save_super_candidates(self, candidates: List[Dict[str, Any]], settings: Dict[str, Any]) -> None:
        """持久化 Super Alpha 候选假设."""
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

    def get_super_candidates(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取 Super Alpha 候选假设列表."""
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
        """记录 Super Alpha 回测结果."""
        self._get_connection().execute(
            """UPDATE super_alpha_candidates SET status=?, alpha_id=COALESCE(NULLIF(?, ''), alpha_id),
            result_json=COALESCE(?, result_json), error_message=COALESCE(NULLIF(?, ''), error_message), updated_at=?
            WHERE candidate_sha=?""",
            (status, alpha_id, self._json(result) if result is not None else None, error_message, self._timestamp(), candidate_sha),
        )
        self._get_connection().commit()

    def enqueue_optimization(
        self,
        alpha_id: str,
        expression: str,
        *,
        sharpe: float = 0.0,
        fitness: float = 0.0,
        turnover: float = 0.0,
        margin: float = 0.0,
        failed_checks: Optional[List[Dict]] = None,
        failed_ra_count: int = 0,
        failed_ppa_count: int = 0,
        optimization_hints: Optional[Dict] = None,
        priority: int = 0,
    ) -> int:
        """将因子加入优化队列."""
        now = self._timestamp()
        conn = self._get_connection()
        cursor = conn.execute(
            """INSERT INTO alpha_optimization_queue
            (alpha_id, expression, sharpe, fitness, turnover, margin,
             failed_checks, failed_ra_count, failed_ppa_count, optimization_hints,
             status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                alpha_id, expression, sharpe, fitness, turnover, margin,
                self._json(failed_checks or []), failed_ra_count, failed_ppa_count,
                self._json(optimization_hints or {}), priority, now, now,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def pop_optimization_task(self) -> Optional[Dict[str, Any]]:
        """取出最高优先级的待优化任务并标记为 optimizing."""
        conn = self._get_connection()
        row = conn.execute(
            """SELECT * FROM alpha_optimization_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, id ASC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        task = dict(row)
        now = self._timestamp()
        conn.execute(
            "UPDATE alpha_optimization_queue SET status = 'optimizing', updated_at = ? WHERE id = ?",
            (now, task["id"]),
        )
        conn.commit()
        task["status"] = "optimizing"
        return task

    def update_optimization_status(self, task_id: int, status: str) -> None:
        """更新优化任务状态."""
        now = self._timestamp()
        self._get_connection().execute(
            "UPDATE alpha_optimization_queue SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, task_id),
        )
        self._get_connection().commit()

    def get_optimization_queue(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """查询优化队列列表."""
        sql = "SELECT * FROM alpha_optimization_queue"
        params: List[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY priority DESC, id ASC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def record_submission_candidate(
        self,
        alpha_id: str,
        expression: str,
        *,
        sharpe: float = 0.0,
        fitness: float = 0.0,
        turnover: float = 0.0,
        margin: float = 0.0,
        sc_value: Optional[float] = None,
        pc_value: Optional[float] = None,
        local_sc: Optional[float] = None,
        local_sc_grade: Optional[str] = None,
        robustness_status: str = "pending",
        robustness_notes: Optional[str] = None,
        pyramid_category: Optional[str] = None,
        pyramid_multiplier: Optional[float] = None,
    ) -> int:
        """录入或更新达标提交候选池."""
        now = self._timestamp()
        conn = self._get_connection()
        cursor = conn.execute(
            """INSERT INTO alpha_submission_candidates
            (alpha_id, expression, sharpe, fitness, turnover, margin,
             sc_value, pc_value, local_sc, local_sc_grade, robustness_status,
             robustness_notes, pyramid_category, pyramid_multiplier, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alpha_id) DO UPDATE SET
                sharpe=excluded.sharpe, fitness=excluded.fitness,
                turnover=excluded.turnover, margin=excluded.margin,
                sc_value=excluded.sc_value, pc_value=excluded.pc_value,
                local_sc=excluded.local_sc, local_sc_grade=excluded.local_sc_grade,
                robustness_status=excluded.robustness_status,
                robustness_notes=excluded.robustness_notes,
                pyramid_category=excluded.pyramid_category,
                pyramid_multiplier=excluded.pyramid_multiplier,
                updated_at=excluded.updated_at""",
            (
                alpha_id, expression, sharpe, fitness, turnover, margin,
                sc_value, pc_value, local_sc, local_sc_grade, robustness_status,
                robustness_notes, pyramid_category, pyramid_multiplier, now, now,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_submission_candidates(
        self,
        *,
        is_submitted: Optional[bool] = None,
        min_sharpe: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询提交候选池列表."""
        sql = "SELECT * FROM alpha_submission_candidates WHERE 1=1"
        params: List[Any] = []
        if is_submitted is not None:
            sql += " AND is_submitted = ?"
            params.append(1 if is_submitted else 0)
        if min_sharpe is not None:
            sql += " AND sharpe >= ?"
            params.append(min_sharpe)
        sql += " ORDER BY sharpe DESC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def mark_candidate_submitted(self, alpha_id: str) -> None:
        """标记候选因子已在平台完成提交."""
        now = self._timestamp()
        conn = self._get_connection()
        conn.execute(
            """UPDATE alpha_submission_candidates
            SET is_submitted = 1, submitted_at = ?, updated_at = ?
            WHERE alpha_id = ?""",
            (now, now, alpha_id),
        )
        conn.commit()

    def mark_candidate_rejected(self, alpha_id: str, reason: str = "") -> None:
        """标记候选因子被审核拒绝."""
        now = self._timestamp()
        conn = self._get_connection()
        conn.execute(
            """UPDATE alpha_submission_candidates
            SET robustness_status = 'fail', robustness_notes = ?, updated_at = ?
            WHERE alpha_id = ?""",
            (reason, now, alpha_id),
        )
        conn.commit()
