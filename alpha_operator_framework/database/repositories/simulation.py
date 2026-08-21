"""回测批次与仿真结果仓储 (Simulation Batch & Results Repository).

管理表:
  - simulation_batches (平台仿真批次与进度管理)
  - simulation_results (单因子仿真结果明细与关联)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from ..base import BaseRepository


class SimulationRepository(BaseRepository):
    """回测批次与仿真结果仓储."""

    @staticmethod
    def compute_sha(expression: str) -> str:
        """计算表达式 SHA256 指纹."""
        return hashlib.sha256(expression.strip().encode("utf-8")).hexdigest()

    @classmethod
    def compute_alpha_sha(cls, expression: str, settings: Dict[str, Any]) -> str:
        """计算包含环境设置的 Alpha 综合指纹."""
        payload = f"{expression.strip()}|{settings.get('region','')}|{settings.get('universe','')}|{settings.get('delay',1)}|{settings.get('decay',0.0)}|{settings.get('neutralization','')}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def create_simulation_batch(self, tasks: List[Dict[str, Any]], settings: Dict[str, Any],
                                simulation_type: str = "REGULAR") -> int:
        """创建仿真批次并初始化关联任务."""
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
        conn.execute(
            """UPDATE alpha_expressions SET batch_id=?, status='pending', updated_at=?
               WHERE expression_sha IN (SELECT expression_sha FROM simulation_results WHERE batch_id=?)""",
            (batch_id, now, batch_id),
        )
        conn.commit()
        return batch_id

    def attach_platform_batch(self, batch_id: int, platform_batch_id: str, platform_location: str) -> None:
        """关联真实平台返回的批次 ID 与查询 Location."""
        now = self._timestamp()
        self._get_connection().execute(
            """UPDATE simulation_batches SET platform_batch_id=?, platform_location=?, status='submitted',
            submitted_at=?, updated_at=? WHERE id=?""",
            (platform_batch_id, platform_location, now, now, batch_id),
        )
        self._get_connection().commit()

    def record_simulation_progress(self, batch_id: int, progress: Any, *, status: str = "polling",
                                   error_message: str = "") -> None:
        """更新批次轮询进度."""
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
        """记录批次内单个因子的仿真结果."""
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
        """刷新批次完成/失败汇总计数."""
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

    def get_simulation_batch(self, batch_id: int) -> Optional[Dict[str, Any]]:
        """获取指定仿真批次信息."""
        row = self._get_connection().execute("SELECT * FROM simulation_batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None

    def get_simulation_results(self, batch_id: int) -> List[Dict[str, Any]]:
        """获取指定批次全部仿真结果列表."""
        rows = self._get_connection().execute(
            "SELECT * FROM simulation_results WHERE batch_id=? ORDER BY sequence_no", (batch_id,)
        ).fetchall()
        return [dict(row) for row in rows]
