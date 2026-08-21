"""Unit & Integration tests for Outbox Worker crash recovery, idempotency, and synthetic mock boundaries."""

import pytest

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.core.outbox_worker import (
    PlatformOutboxWorker,
    compute_idempotency_key,
    validate_platform_evidence,
)
from alpha_operator_framework.domain.evidence import EvidenceLevel


def test_outbox_worker_mock_returns_pure_synthetic():
    """测试默认 Mock 仿真器强制仅返回 synthetic，绝不伪装为 platform_is."""
    event_store = EventStore()
    artifact_store = ArtifactStore()
    worker = PlatformOutboxWorker(event_store, artifact_store)

    ikey = compute_idempotency_key("pol_mock", "cand_01", {"region": "GBR"}, "discovery_is")
    req_evt = Event.create(
        event_type=EventType.SIMULATION_REQUESTED,
        stream_id="stream_mock",
        payload={
            "idempotency_key": ikey,
            "candidate_sha": "cand_01",
            "expression": "rank(returns)",
            "settings": {"region": "GBR"},
        },
    )
    event_store.append(req_evt)

    emitted = worker.process_pending_outbox("stream_mock")
    assert len(emitted) == 2  # Accepted + Completed

    comp_evt = next(e for e in emitted if e.event_type == EventType.SIMULATION_COMPLETED)
    # 必须为 synthetic
    assert comp_evt.payload["evidence_level"] == EvidenceLevel.SYNTHETIC.value


def test_outbox_worker_crash_recovery_from_accepted():
    """测试进程在 SIMULATION_ACCEPTED 之后崩溃时，重启后能自动从 accepted 恢复并推进至 COMPLETED."""
    event_store = EventStore()
    artifact_store = ArtifactStore()

    call_count = 0

    def mock_real_platform(expr, settings):
        nonlocal call_count
        call_count += 1
        return {
            "alpha_id": "REAL_ALPHA_99",
            "sharpe": 1.75,
            "fitness": 1.45,
            "turnover": 0.15,
            "returns": 0.22,
            "drawdown": 0.05,
            "evidence_level": "platform_is",
        }

    # 1. 模拟崩溃前产生了一个 REQUESTED 和一个 ACCEPTED 事件 (进程崩溃中断)
    ikey = compute_idempotency_key("pol_crash", "cand_crash_01", {"region": "GBR"}, "discovery_is")
    req_evt = Event.create(
        event_type=EventType.SIMULATION_REQUESTED,
        stream_id="stream_crash",
        payload={
            "idempotency_key": ikey,
            "candidate_sha": "cand_crash_01",
            "expression": "rank(returns)",
            "settings": {"region": "GBR"},
        },
    )
    acc_evt = Event.create(
        event_type=EventType.SIMULATION_ACCEPTED,
        stream_id="stream_crash",
        payload={
            "idempotency_key": ikey,
            "candidate_sha": "cand_crash_01",
            "platform_sim_id": "sim_crash_123",
            "location": "/simulations/sim_crash_123",
            "status": "ACCEPTED",
        },
    )
    event_store.append(req_evt)
    event_store.append(acc_evt)

    # 2. 新启动的 Worker 实例 (模拟进程重启)
    recovered_worker = PlatformOutboxWorker(event_store, artifact_store, simulator_fn=mock_real_platform)

    # 3. 执行崩溃恢复
    emitted = recovered_worker.process_pending_outbox("stream_crash")
    assert len(emitted) == 1  # 恢复产出 1 个 SIMULATION_COMPLETED
    assert emitted[0].event_type == EventType.SIMULATION_COMPLETED
    assert emitted[0].payload["evidence_level"] == EvidenceLevel.PLATFORM_IS.value
    assert emitted[0].payload["alpha_id"] == "REAL_ALPHA_99"
    assert call_count == 1

    # 4. 重复调用 Worker，幂等跳过，不再重复执行
    re_emitted = recovered_worker.process_pending_outbox("stream_crash")
    assert len(re_emitted) == 0
    assert call_count == 1
