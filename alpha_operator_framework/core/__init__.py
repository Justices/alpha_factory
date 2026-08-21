"""事件溯源量化研究核心 (Event-Sourced Quantitative Research Core).

实现完全可重放、不可变工件寻址、异步 Outbox Saga 与 A/B 分支对照实验.
"""

from alpha_operator_framework.core.artifacts import ArtifactMetadata, ArtifactStore
from alpha_operator_framework.core.engine import EventSourcedResearchEngine
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.core.graph import ExperimentGraph, GraphEdge, GraphNode
from alpha_operator_framework.core.outbox_worker import PlatformOutboxWorker, compute_idempotency_key
from alpha_operator_framework.core.policy import (
    BudgetPolicy,
    ResearchPolicy,
    SelectionPolicy,
    StopPolicy,
    ValidationPartitions,
)
from alpha_operator_framework.core.projections import (
    CandidateView,
    FamilyStatsView,
    OutboxItemView,
    ProjectionEngine,
)

__all__ = [
    "ArtifactMetadata",
    "ArtifactStore",
    "BudgetPolicy",
    "CandidateView",
    "Event",
    "EventSourcedResearchEngine",
    "EventStore",
    "EventType",
    "ExperimentGraph",
    "FamilyStatsView",
    "GraphEdge",
    "GraphNode",
    "OutboxItemView",
    "PlatformOutboxWorker",
    "ProjectionEngine",
    "ResearchPolicy",
    "SelectionPolicy",
    "StopPolicy",
    "ValidationPartitions",
    "compute_idempotency_key",
]
