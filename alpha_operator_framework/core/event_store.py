"""事件溯源研究内核 — 追加写事件存储引擎 (Append-Only Event Store).

实现高吞吐、只追加 (Append-Only) 的事件流存储，支持按全局 Offset、Stream ID 与 EventType 重放。
遵循高内聚、低耦合架构，数据底层访问统一委托给仓储层 (AlphaDatabase / EventRepository)，零 SQL/零 sqlite3 依赖。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, List, Optional, Sequence, Union

from alpha_operator_framework.core.events import Event, EventType

logger = logging.getLogger(__name__)


class EventStore:
    """事件存储引擎 (Event Store).
    
    默认支持纯内存模式（隔离且高速，适合测试与轻量沙盒），
    亦支持持久化模式（自动委托给统一仓储 AlphaDatabase 进行落库与重放）。
    """

    def __init__(
        self,
        persistent: bool = False,
        repository: Optional[Any] = None,
        in_memory: bool = False,
    ):
        """初始化事件存储引擎.

        Args:
            persistent: 若为 True，则启用持久化模式，事件将落库保存。
            repository: 持久化仓储；启用持久化时必须注入。
            in_memory: 显式使用纯内存模式，优先级最高。
        """
        # 使用线程锁保证并发 append 时事件序列的线性一致性（内存列表非线程安全）
        self._lock = threading.Lock()
        self._memory_events: List[Event] = []
        if persistent and repository is None and not in_memory:
            raise ValueError("persistent EventStore requires an injected repository")
        self._persistent = repository is not None and not in_memory
        self._repository = repository if self._persistent else None

        logger.info(
            "EventStore 初始化完成：persistent=%s, repository=%s",
            self._persistent,
            type(self._repository).__name__ if self._repository is not None else None,
        )

    @property
    def is_persistent(self) -> bool:
        """是否处于持久化模式."""
        return self._persistent

    def append(self, event: Event) -> int:
        """追加单个事件到事件流，返回全局递增 Offset.

        Args:
            event: 要写入的事件对象，包含 stream_id、event_type 等完整信息。

        Returns:
            事件在全局事件流中的递增 Offset（持久化模式由数据库分配，内存模式自增）。
        """
        with self._lock:
            if self._persistent and self._repository:
                offset = self._repository.append_event(
                    event_id=event.event_id,
                    stream_id=event.stream_id,
                    event_type=event.event_type.value,
                    schema_version=event.schema_version,
                    payload_json=json.dumps(event.payload, ensure_ascii=False),
                    payload_ref=event.payload_ref,
                    occurred_at=event.occurred_at,
                    actor=event.actor,
                    metadata_json=json.dumps(event.metadata, ensure_ascii=False),
                )
            else:
                offset = len(self._memory_events) + 1
            self._memory_events.append(event)
            return offset

    def append_batch(self, events: Sequence[Event]) -> List[int]:
        """批量追加事件到事件流.

        Args:
            events: 要批量写入的事件序列，顺序对应返回的 offset 序列。

        Returns:
            与 events 顺序一一对应的全局 Offset 列表；若输入为空则返回空列表。
        """
        if not events:
            return []
        with self._lock:
            if self._persistent and self._repository:
                rows = [
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
                    )
                    for evt in events
                ]
                offsets = self._repository.append_events_batch(rows)
            else:
                base = len(self._memory_events)
                offsets = [base + i + 1 for i in range(len(events))]
            self._memory_events.extend(events)
            return offsets

    def read_stream(self, stream_id: str, from_offset: int = 0) -> List[Event]:
        """读取指定 Stream ID 的事件序列."""
        with self._lock:
            if self._persistent and self._repository:
                rows = self._repository.read_events_by_stream(stream_id, from_offset)
                result = [
                    Event(
                        event_id=r["event_id"],
                        stream_id=r["stream_id"],
                        event_type=EventType(r["event_type"]),
                        schema_version=r["schema_version"],
                        payload=json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                        payload_ref=r.get("payload_ref"),
                        occurred_at=r["occurred_at"],
                        actor=r["actor"],
                        metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                    )
                    for r in rows
                ]
            else:
                result = [
                    e for e in self._memory_events
                    if e.stream_id == stream_id
                ]
            logger.info("读取流 %s 事件列表，起始 offset=%d，返回 %d 个事件", stream_id, from_offset, len(result))
            return result

    def read_all(self, from_offset: int = 0, limit: Optional[int] = None) -> List[Event]:
        """按全局 Offset 读取全部事件流 (用于投影重放 Replay)."""
        with self._lock:
            if self._persistent and self._repository:
                rows = self._repository.read_all_events(from_offset, limit)
                result = [
                    Event(
                        event_id=r["event_id"],
                        stream_id=r["stream_id"],
                        event_type=EventType(r["event_type"]),
                        schema_version=r["schema_version"],
                        payload=json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                        payload_ref=r.get("payload_ref"),
                        occurred_at=r["occurred_at"],
                        actor=r["actor"],
                        metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                    )
                    for r in rows
                ]
            else:
                events = self._memory_events[from_offset:]
                if limit is not None:
                    events = events[:limit]
                result = events
            logger.info("按全局 Offset 读取全部事件流，起始 offset=%d，限制数量=%s，实际返回 %d 个事件", from_offset, limit, len(result))
            return result

    def read_by_type(self, event_type: Union[EventType, str], from_offset: int = 0) -> List[Event]:
        """按事件类型读取事件流."""
        etype_str = event_type.value if isinstance(event_type, EventType) else str(event_type)
        with self._lock:
            if self._persistent and self._repository:
                rows = self._repository.read_events_by_type(etype_str, from_offset)
                result = [
                    Event(
                        event_id=r["event_id"],
                        stream_id=r["stream_id"],
                        event_type=EventType(r["event_type"]),
                        schema_version=r["schema_version"],
                        payload=json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                        payload_ref=r.get("payload_ref"),
                        occurred_at=r["occurred_at"],
                        actor=r["actor"],
                        metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                    )
                    for r in rows
                ]
            else:
                result = [
                    e for e in self._memory_events
                    if (e.event_type.value if isinstance(e.event_type, EventType) else e.event_type) == etype_str
                ]
            logger.info("按类型 %s 读取事件流，起始 offset=%d，返回 %d 个事件", etype_str, from_offset, len(result))
            return result
