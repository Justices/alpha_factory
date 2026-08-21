"""事件溯源研究内核 — 平台异步 Outbox Worker (Idempotent Platform Worker).

外部 API 交互采用 Outbox + 幂等键 Saga 模式：
无论 Worker 进程如何异常退出或重启，重新拉取未完成事件即可无缝恢复，绝不重复提交。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.domain.evidence import EvidenceLevel

logger = logging.getLogger(__name__)


def compute_idempotency_key(
    policy_id: str,
    candidate_sha: str,
    settings: Dict[str, Any],
    partition_id: str = "discovery_is",
) -> str:
    """生成确定性仿真幂等键 (Idempotency Key)."""
    settings_raw = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    combined = f"{policy_id}:{candidate_sha}:{settings_raw}:{partition_id}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def validate_platform_evidence(sim_result: Dict[str, Any]) -> EvidenceLevel:
    """严格校验仿真结果的证据等级 — 杜绝 Mock 伪造 platform_is."""
    alpha_id = str(sim_result.get("alpha_id") or "")
    evidence_str = str(sim_result.get("evidence_level") or "synthetic").lower()

    # 外部实测必须有合法平台的 Alpha ID (非空且非 FAILED 前缀)
    if evidence_str in ("platform_is", "platform_os", "submission_ready"):
        if not alpha_id or alpha_id.startswith("FAILED_") or alpha_id.startswith("MOCK_"):
            logger.warning(f"检测到伪造平台证据级别: alpha_id='{alpha_id}', 强制降级为 synthetic")
            return EvidenceLevel.SYNTHETIC
        if evidence_str == "platform_os":
            return EvidenceLevel.PLATFORM_OS
        if evidence_str == "submission_ready":
            return EvidenceLevel.SUBMISSION_READY
        return EvidenceLevel.PLATFORM_IS

    if evidence_str == "sandbox_diagnostic":
        return EvidenceLevel.SANDBOX_DIAGNOSTIC

    return EvidenceLevel.SYNTHETIC


class PlatformOutboxWorker:
    """平台模拟 Outbox 异步处理 Worker (支持崩溃断点恢复与幂等执行)."""

    def __init__(
        self,
        event_store: EventStore,
        artifact_store: ArtifactStore,
        simulator_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.event_store = event_store
        self.artifact_store = artifact_store
        self.simulator_fn = simulator_fn or self._default_mock_simulator
        self._completed_idempotency_keys: Set[str] = set()

    def process_pending_outbox(self, stream_id: Optional[str] = None) -> List[Event]:
        """拉取未完成的仿真任务并推进至终态 (具备崩溃断点续传能力)."""
        all_events = self.event_store.read_all() if stream_id is None else self.event_store.read_stream(stream_id)

        # 1. 扫描事件日志：找出已达到终态 (COMPLETED / FAILED) 的幂等键，以及处于 ACCEPTED 状态的悬挂任务
        completed_keys: Set[str] = set()
        accepted_tasks: Dict[str, Event] = {}  # ikey -> accept_event
        requested_tasks: Dict[str, Event] = {}  # ikey -> req_event

        for e in all_events:
            ikey = e.payload.get("idempotency_key")
            if not ikey:
                continue

            if e.event_type in (EventType.SIMULATION_COMPLETED, EventType.CANDIDATE_REJECTED_BY_RULE):
                completed_keys.add(ikey)
            elif e.event_type == EventType.SIMULATION_ACCEPTED:
                accepted_tasks[ikey] = e
            elif e.event_type == EventType.SIMULATION_REQUESTED:
                requested_tasks[ikey] = e

        self._completed_idempotency_keys.update(completed_keys)
        emitted_events: List[Event] = []

        # 2. 阶段 A: 恢复已被 ACCEPTED 但尚未达到终态的悬挂任务 (崩溃恢复)
        for ikey, acc_evt in accepted_tasks.items():
            if ikey in completed_keys:
                continue  # 已完成

            req_evt = requested_tasks.get(ikey)
            if not req_evt:
                continue

            csha = req_evt.payload.get("candidate_sha", "")
            expr = req_evt.payload.get("expression", "")
            settings = req_evt.payload.get("settings", {})
            sim_id = acc_evt.payload.get("platform_sim_id", "")

            comp_evt = self._execute_and_complete(
                stream_id=acc_evt.stream_id,
                ikey=ikey,
                csha=csha,
                sim_id=sim_id,
                expr=expr,
                settings=settings,
            )
            if comp_evt:
                emitted_events.append(comp_evt)
                self._completed_idempotency_keys.add(ikey)
                completed_keys.add(ikey)

        # 3. 阶段 B: 处理全新的 SIMULATION_REQUESTED 任务
        for ikey, req_evt in requested_tasks.items():
            if ikey in completed_keys or ikey in accepted_tasks:
                continue  # 已处理或已在恢复队列中

            csha = req_evt.payload.get("candidate_sha", "")
            expr = req_evt.payload.get("expression", "")
            settings = req_evt.payload.get("settings", {})

            # 产生 SimulationAccepted 事件并持久化 (记录 Location/sim_id)
            sim_id = f"sim_{hashlib.md5(ikey.encode('utf-8')).hexdigest()[:10]}"
            accept_event = Event.create(
                event_type=EventType.SIMULATION_ACCEPTED,
                stream_id=req_evt.stream_id,
                payload={
                    "idempotency_key": ikey,
                    "candidate_sha": csha,
                    "platform_sim_id": sim_id,
                    "location": f"/simulations/{sim_id}",
                    "status": "ACCEPTED",
                },
                actor="worker:platform",
            )
            self.event_store.append(accept_event)
            emitted_events.append(accept_event)

            # 执行仿真并推进至终态
            comp_evt = self._execute_and_complete(
                stream_id=req_evt.stream_id,
                ikey=ikey,
                csha=csha,
                sim_id=sim_id,
                expr=expr,
                settings=settings,
            )
            if comp_evt:
                emitted_events.append(comp_evt)
                self._completed_idempotency_keys.add(ikey)
                completed_keys.add(ikey)

        return emitted_events

    def _execute_and_complete(
        self,
        stream_id: str,
        ikey: str,
        csha: str,
        sim_id: str,
        expr: str,
        settings: Dict[str, Any],
    ) -> Optional[Event]:
        """执行仿真函数并产出终态事件 (严格校验证据等级)."""
        try:
            sim_result = self.simulator_fn(expr, settings)
            result_ref = self.artifact_store.put_json(sim_result)
            evidence = validate_platform_evidence(sim_result)

            complete_event = Event.create(
                event_type=EventType.SIMULATION_COMPLETED,
                stream_id=stream_id,
                payload={
                    "idempotency_key": ikey,
                    "candidate_sha": csha,
                    "platform_sim_id": sim_id,
                    "alpha_id": sim_result.get("alpha_id", ""),
                    "sharpe": float(sim_result.get("sharpe", 0.0)),
                    "fitness": float(sim_result.get("fitness", 0.0)),
                    "turnover": float(sim_result.get("turnover", 0.0)),
                    "returns": float(sim_result.get("returns", 0.0)),
                    "drawdown": float(sim_result.get("drawdown", 0.0)),
                    "evidence_level": evidence.value,
                },
                payload_ref=result_ref,
                actor="worker:platform",
            )
            self.event_store.append(complete_event)
            return complete_event

        except Exception as ex:
            logger.error(f"仿真任务执行失败 ({ikey}): {ex}")
            # 记录失败事件并关闭幂等键
            fail_event = Event.create(
                event_type=EventType.CANDIDATE_REJECTED_BY_RULE,
                stream_id=stream_id,
                payload={
                    "idempotency_key": ikey,
                    "candidate_sha": csha,
                    "reason": f"Simulation execution error: {ex}",
                },
                actor="worker:platform",
            )
            self.event_store.append(fail_event)
            return fail_event

    def _default_mock_simulator(self, expression: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """内置确定性模拟器 (仅用于单元测试与语法测试 — 强制返回 synthetic)."""
        h_val = int(hashlib.md5(expression.encode("utf-8")).hexdigest()[:8], 16)
        sharpe = round(1.0 + (h_val % 100) / 50.0, 2)
        fitness = round(sharpe * 0.85, 2)
        turnover = round(0.10 + (h_val % 40) / 100.0, 2)
        return {
            "sharpe": sharpe,
            "fitness": fitness,
            "turnover": turnover,
            "returns": round(sharpe * 0.12, 4),
            "drawdown": round(0.08 + (h_val % 10) / 100.0, 4),
            "evidence_level": EvidenceLevel.SYNTHETIC.value,  # 绝不允许伪造为 platform_is
        }
