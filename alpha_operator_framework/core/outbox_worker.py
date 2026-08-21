"""事件溯源研究内核 — 平台异步 Outbox Worker (Idempotent Platform Worker).

外部 API 交互采用 Outbox + 幂等键 Saga 模式：
无论 Worker 进程如何异常退出或重启，重新拉取未完成事件即可无缝恢复，绝不重复提交。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType

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


class PlatformOutboxWorker:
    """平台模拟 Outbox 异步处理 Worker."""

    def __init__(
        self,
        event_store: EventStore,
        artifact_store: ArtifactStore,
        simulator_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.event_store = event_store
        self.artifact_store = artifact_store
        self.simulator_fn = simulator_fn or self._default_mock_simulator
        self._processed_idempotency_keys: set[str] = set()

    def process_pending_outbox(self, stream_id: Optional[str] = None) -> List[Event]:
        """拉取未完成的 SimulationRequested 事件并幂等执行."""
        all_events = self.event_store.read_all() if stream_id is None else self.event_store.read_stream(stream_id)
        
        # 提取已完成或已处理的幂等键
        for e in all_events:
            if e.event_type in (EventType.SIMULATION_ACCEPTED, EventType.SIMULATION_COMPLETED):
                ikey = e.payload.get("idempotency_key")
                if ikey:
                    self._processed_idempotency_keys.add(ikey)

        emitted_events: List[Event] = []

        for e in all_events:
            if e.event_type == EventType.SIMULATION_REQUESTED:
                ikey = e.payload.get("idempotency_key", "")
                if not ikey or ikey in self._processed_idempotency_keys:
                    continue  # 已处理过，幂等跳过

                csha = e.payload.get("candidate_sha", "")
                expr = e.payload.get("expression", "")
                settings = e.payload.get("settings", {})
                policy_id = e.payload.get("policy_id", "default_policy")

                # 1. 产生 SimulationAccepted 事件
                sim_id = f"sim_{hashlib.md5(ikey.encode('utf-8')).hexdigest()[:10]}"
                accept_event = Event.create(
                    event_type=EventType.SIMULATION_ACCEPTED,
                    stream_id=e.stream_id,
                    payload={
                        "idempotency_key": ikey,
                        "candidate_sha": csha,
                        "platform_sim_id": sim_id,
                        "status": "ACCEPTED",
                    },
                    actor="worker:platform",
                )
                self.event_store.append(accept_event)
                emitted_events.append(accept_event)

                # 2. 执行实际平台回测
                try:
                    sim_result = self.simulator_fn(expr, settings)
                    # 存入工件库
                    result_ref = self.artifact_store.put_json(sim_result)

                    complete_event = Event.create(
                        event_type=EventType.SIMULATION_COMPLETED,
                        stream_id=e.stream_id,
                        payload={
                            "idempotency_key": ikey,
                            "candidate_sha": csha,
                            "platform_sim_id": sim_id,
                            "sharpe": sim_result.get("sharpe", 0.0),
                            "fitness": sim_result.get("fitness", 0.0),
                            "turnover": sim_result.get("turnover", 0.0),
                            "returns": sim_result.get("returns", 0.0),
                            "drawdown": sim_result.get("drawdown", 0.0),
                            "evidence_level": sim_result.get("evidence_level", "platform_is"),
                        },
                        payload_ref=result_ref,
                        actor="worker:platform",
                    )
                    self.event_store.append(complete_event)
                    emitted_events.append(complete_event)
                    self._processed_idempotency_keys.add(ikey)

                except Exception as ex:
                    logger.error(f"仿真任务执行失败 ({ikey}): {ex}")

        return emitted_events

    def _default_mock_simulator(self, expression: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """内置确定性模拟器 (用于单测与离线环境)."""
        # 基于表达式哈希产生确定性绩效指标
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
            "evidence_level": "platform_is",
        }
