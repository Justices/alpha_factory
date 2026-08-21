"""事件日志流与多重检验试验账本仓储 (Event & Trial Ledger Repository).

管理表:
  - event_log (追加写事件溯源流)
  - trial_ledger (全生命周期多重检验试验账本)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Union

from ..base import BaseRepository


class EventLedgerRepository(BaseRepository):
    """事件日志流与多重检验试验账本仓储."""

    def record_trial(
        self,
        trial_id: str,
        expression: str,
        family: str = "default",
        region: str = "GBR",
        universe: str = "TOP700",
        metrics: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> None:
        """持久化记录试验自由度."""
        now = created_at or self._timestamp()
        conn = self._get_connection()
        conn.execute(
            """INSERT OR IGNORE INTO trial_ledger
            (trial_id, expression, family, region, universe, metrics_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (trial_id, expression, family, region, universe, self._json(metrics or {}), now),
        )
        conn.commit()

    def get_trial_counts_by_family(self) -> Dict[str, int]:
        """获取各模板族累计试验次数."""
        conn = self._get_connection()
        rows = conn.execute("SELECT family, COUNT(*) FROM trial_ledger GROUP BY family").fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def get_total_trial_count(self) -> int:
        """获取全生命周期累计试验总数."""
        conn = self._get_connection()
        row = conn.execute("SELECT COUNT(*) FROM trial_ledger").fetchone()
        return int(row[0]) if row else 0

    def append_event(
        self,
        event_id: str,
        stream_id: str,
        event_type: str,
        schema_version: int,
        payload_json: str,
        payload_ref: Optional[str],
        occurred_at: str,
        actor: str,
        metadata_json: str,
    ) -> int:
        """追加单个事件到事件日志表，返回全局递增 offset."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO event_log (
                event_id, stream_id, event_type, schema_version,
                payload, payload_ref, occurred_at, actor, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, stream_id, event_type, schema_version,
                payload_json, payload_ref, occurred_at, actor, metadata_json,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def append_events_batch(
        self,
        event_rows: Sequence[tuple],
    ) -> List[int]:
        """批量追加事件到事件日志表，返回全局 offset 列表."""
        if not event_rows:
            return []
        conn = self._get_connection()
        cursor = conn.cursor()
        offsets: List[int] = []
        for row in event_rows:
            cursor.execute(
                """INSERT INTO event_log (
                    event_id, stream_id, event_type, schema_version,
                    payload, payload_ref, occurred_at, actor, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
            offsets.append(cursor.lastrowid or 0)
        conn.commit()
        return offsets

    def read_events_by_stream(self, stream_id: str, from_offset: int = 0) -> List[Dict[str, Any]]:
        """按 stream_id 查询事件记录."""
        conn = self._get_connection()
        query = """
            SELECT event_id, stream_id, event_type, schema_version,
                   payload, payload_ref, occurred_at, actor, metadata
            FROM event_log
            WHERE stream_id = ? AND global_offset >= ?
            ORDER BY global_offset ASC
        """
        rows = conn.execute(query, (stream_id, from_offset)).fetchall()
        return [
            {
                "event_id": r[0],
                "stream_id": r[1],
                "event_type": r[2],
                "schema_version": r[3],
                "payload": r[4],
                "payload_ref": r[5],
                "occurred_at": r[6],
                "actor": r[7],
                "metadata": r[8],
            }
            for r in rows
        ]

    def read_all_events(self, from_offset: int = 0, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """全局读取事件流."""
        conn = self._get_connection()
        query = """
            SELECT event_id, stream_id, event_type, schema_version,
                   payload, payload_ref, occurred_at, actor, metadata
            FROM event_log
            WHERE global_offset >= ?
            ORDER BY global_offset ASC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = conn.execute(query, (from_offset,)).fetchall()
        return [
            {
                "event_id": r[0],
                "stream_id": r[1],
                "event_type": r[2],
                "schema_version": r[3],
                "payload": r[4],
                "payload_ref": r[5],
                "occurred_at": r[6],
                "actor": r[7],
                "metadata": r[8],
            }
            for r in rows
        ]

    def read_events_by_type(self, event_type: str, from_offset: int = 0) -> List[Dict[str, Any]]:
        """按事件类型读取事件流."""
        conn = self._get_connection()
        query = """
            SELECT event_id, stream_id, event_type, schema_version,
                   payload, payload_ref, occurred_at, actor, metadata
            FROM event_log
            WHERE event_type = ? AND global_offset >= ?
            ORDER BY global_offset ASC
        """
        rows = conn.execute(query, (event_type, from_offset)).fetchall()
        return [
            {
                "event_id": r[0],
                "stream_id": r[1],
                "event_type": r[2],
                "schema_version": r[3],
                "payload": r[4],
                "payload_ref": r[5],
                "occurred_at": r[6],
                "actor": r[7],
                "metadata": r[8],
            }
            for r in rows
        ]
