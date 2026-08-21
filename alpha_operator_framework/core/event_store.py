"""事件溯源研究内核 — 追加写事件存储引擎 (Append-Only Event Store).

实现高吞吐、只追加 (Append-Only) 的事件流存储，支持按全局 Offset、Stream ID 与 EventType 重放。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from alpha_operator_framework.core.events import Event, EventType


class EventStore:
    """事件存储引擎 (Event Store)."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = str(db_path) if db_path else ":memory:"
        self._lock = threading.Lock()
        self._memory_events: List[Event] = []
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 事件表结构与索引."""
        with self._lock:
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("""
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
                    metadata TEXT NOT NULL
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_evt_stream ON event_log(stream_id, global_offset)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_evt_type ON event_log(event_type, global_offset)")
            self._conn.commit()

    def append(self, event: Event) -> int:
        """追加单个事件到事件流，返回全局递增 Offset."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO event_log (
                    event_id, stream_id, event_type, schema_version,
                    payload, payload_ref, occurred_at, actor, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.stream_id,
                    event.event_type.value,
                    event.schema_version,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.payload_ref,
                    event.occurred_at,
                    event.actor,
                    json.dumps(event.metadata, ensure_ascii=False),
                ),
            )
            self._conn.commit()
            offset = cursor.lastrowid or 0
            self._memory_events.append(event)
            return offset

    def append_batch(self, events: Sequence[Event]) -> List[int]:
        """批量追加事件到事件流."""
        if not events:
            return []
        offsets: List[int] = []
        with self._lock:
            cursor = self._conn.cursor()
            for evt in events:
                cursor.execute(
                    """
                    INSERT INTO event_log (
                        event_id, stream_id, event_type, schema_version,
                        payload, payload_ref, occurred_at, actor, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evt.event_id,
                        evt.stream_id,
                        evt.event_type.value,
                        evt.schema_version,
                        json.dumps(evt.payload, ensure_ascii=False),
                        evt.payload_ref,
                        evt.occurred_at,
                        evt.actor,
                        json.dumps(evt.metadata, ensure_ascii=False),
                    ),
                )
                offsets.append(cursor.lastrowid or 0)
                self._memory_events.append(evt)
            self._conn.commit()
        return offsets

    def read_stream(self, stream_id: str, from_offset: int = 0) -> List[Event]:
        """读取指定 Stream ID 的事件序列."""
        query = """
            SELECT event_id, stream_id, event_type, schema_version,
                   payload, payload_ref, occurred_at, actor, metadata
            FROM event_log
            WHERE stream_id = ? AND global_offset >= ?
            ORDER BY global_offset ASC
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, (stream_id, from_offset))
            rows = cursor.fetchall()

        events: List[Event] = []
        for r in rows:
            events.append(
                Event(
                    event_id=r[0],
                    stream_id=r[1],
                    event_type=EventType(r[2]),
                    schema_version=r[3],
                    payload=json.loads(r[4]),
                    payload_ref=r[5],
                    occurred_at=r[6],
                    actor=r[7],
                    metadata=json.loads(r[8]),
                )
            )
        return events

    def read_all(self, from_offset: int = 0, limit: Optional[int] = None) -> List[Event]:
        """按全局 Offset 读取全部事件流 (用于投影重放 Replay)."""
        query = """
            SELECT event_id, stream_id, event_type, schema_version,
                   payload, payload_ref, occurred_at, actor, metadata
            FROM event_log
            WHERE global_offset >= ?
            ORDER BY global_offset ASC
        """
        if limit:
            query += f" LIMIT {int(limit)}"

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, (from_offset,))
            rows = cursor.fetchall()

        events: List[Event] = []
        for r in rows:
            events.append(
                Event(
                    event_id=r[0],
                    stream_id=r[1],
                    event_type=EventType(r[2]),
                    schema_version=r[3],
                    payload=json.loads(r[4]),
                    payload_ref=r[5],
                    occurred_at=r[6],
                    actor=r[7],
                    metadata=json.loads(r[8]),
                )
            )
        return events
