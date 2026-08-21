"""事件溯源研究内核 — 事件模型定义 (Event Sourced Research Core: Events).

最小事件集合与不可变事件事实体系 (符合 2026-08-21 事件溯源重构设计规范).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    """事件类型枚举 (不可变历史事实)."""

    # 1. 策略与实验图生命周期
    POLICY_CREATED = "PolicyCreated"
    PARTITION_LOCKED = "PartitionLocked"
    FIELD_SNAPSHOT_CAPTURED = "FieldSnapshotCaptured"
    HYPOTHESIS_REGISTERED = "HypothesisRegistered"

    # 2. 候选生成与先验打分
    CANDIDATE_GENERATED = "CandidateGenerated"
    CANDIDATE_REJECTED_BY_RULE = "CandidateRejectedByRule"
    CANDIDATE_SCORED = "CandidateScored"

    # 3. 批次分配与平台仿真 (Outbox 模式)
    BATCH_ALLOCATED = "BatchAllocated"
    SIMULATION_REQUESTED = "SimulationRequested"
    SIMULATION_ACCEPTED = "SimulationAccepted"
    SIMULATION_POLLED = "SimulationPolled"
    SIMULATION_COMPLETED = "SimulationCompleted"

    # 4. 验证与相关性
    VALIDATION_COMPUTED = "ValidationComputed"
    CORRELATION_CHECKED = "CorrelationChecked"

    # 5. 决策与治理
    DECISION_PROPOSED = "DecisionProposed"
    DECISION_APPROVED = "DecisionApproved"
    DECISION_REJECTED = "DecisionRejected"

    # 6. 提交与监控
    SUBMISSION_REQUESTED = "SubmissionRequested"
    SUBMISSION_CONFIRMED = "SubmissionConfirmed"
    MONITORING_OBSERVED = "MonitoringObserved"
    CANDIDATE_RETIRED = "CandidateRetired"


@dataclass(frozen=True)
class Event:
    """不可变事件事实 (Event Entity)."""

    event_id: str
    stream_id: str                                  # 聚合根标识 (如 exp_001 或 cand_sha256)
    event_type: EventType
    schema_version: int = 1
    payload: Dict[str, Any] = field(default_factory=dict)
    payload_ref: Optional[str] = None              # Artifact 内容寻址 Hash (SHA256)
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    actor: str = "system"                          # 触发主体: system / planner / worker / human:username
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        event_type: EventType,
        stream_id: str,
        payload: Optional[Dict[str, Any]] = None,
        payload_ref: Optional[str] = None,
        actor: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """便捷构造事件."""
        return cls(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            stream_id=stream_id,
            event_type=event_type,
            schema_version=1,
            payload=payload or {},
            payload_ref=payload_ref,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为标准字典."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Event:
        """从字典反序列化."""
        d = dict(data)
        d["event_type"] = EventType(d["event_type"])
        return cls(**d)
