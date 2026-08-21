"""事件溯源研究内核 — 核心引擎与 A/B 对照实验控制器 (Event-Sourced Research Engine).

整合 Policy、ArtifactStore、EventStore、OutboxWorker、ProjectionEngine 与 A/B 分支比较。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional, Sequence

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.core.graph import ExperimentGraph
from alpha_operator_framework.core.outbox_worker import PlatformOutboxWorker, compute_idempotency_key
from alpha_operator_framework.core.policy import ResearchPolicy
from alpha_operator_framework.core.projections import ProjectionEngine


class EventSourcedResearchEngine:
    """事件溯源研究引擎核心."""

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        artifact_store: Optional[ArtifactStore] = None,
    ):
        self.event_store = event_store or EventStore()
        self.artifact_store = artifact_store or ArtifactStore()
        self.projections = ProjectionEngine()
        self.worker = PlatformOutboxWorker(self.event_store, self.artifact_store)

    def create_experiment(
        self,
        policy: ResearchPolicy,
        graph_id: Optional[str] = None,
        random_seed: int = 42,
    ) -> ExperimentGraph:
        """从策略初始化实验图谱并持久化初始事件."""
        gid = graph_id or f"exp_{uuid.uuid4().hex[:12]}"
        stream_id = gid
        graph = ExperimentGraph(graph_id=gid, policy_id=policy.policy_id, random_seed=random_seed)

        # 1. 存储策略工件
        policy_ref = self.artifact_store.put_json(policy.to_dict())

        # 2. 发出 PolicyCreated 事件
        e1 = Event.create(
            event_type=EventType.POLICY_CREATED,
            stream_id=stream_id,
            payload={"policy_id": policy.policy_id, "version": policy.version},
            payload_ref=policy_ref,
        )
        self.event_store.append(e1)

        # 3. 发出 PartitionLocked 事件 (严格锁死时间窗口)
        e2 = Event.create(
            event_type=EventType.PARTITION_LOCKED,
            stream_id=stream_id,
            payload={
                "discovery_is": policy.validation.discovery_is,
                "validation": policy.validation.validation,
                "locked_oos": policy.validation.locked_oos,
            },
        )
        self.event_store.append(e2)

        return graph

    def plan_and_simulate(
        self,
        graph: ExperimentGraph,
        policy: ResearchPolicy,
        candidates: Sequence[Dict[str, Any]],
        actor: str = "planner",
    ) -> List[str]:
        """批量计划候选、生成不可变事件、提交 Outbox 并执行仿真."""
        stream_id = graph.graph_id
        emitted_candidate_shas: List[str] = []

        for cand in candidates:
            expr = cand.get("expression", "")
            fam = cand.get("family", "default")
            csha = hashlib.sha256(expr.encode("utf-8")).hexdigest()

            # 检查因子族停止规则
            stats = self.projections.family_stats.get(fam)
            if stats and policy.should_stop_family(stats.total_trials, stats.successful_trials):
                # 记录拒绝事件
                rej_e = Event.create(
                    event_type=EventType.CANDIDATE_REJECTED_BY_RULE,
                    stream_id=stream_id,
                    payload={"candidate_sha": csha, "reason": f"Family {fam} stopped due to low hit-rate"},
                    actor=actor,
                )
                self.event_store.append(rej_e)
                continue

            # 1. 生成 CandidateGenerated 事件
            cand_ref = self.artifact_store.put_json(cand)
            gen_e = Event.create(
                event_type=EventType.CANDIDATE_GENERATED,
                stream_id=stream_id,
                payload={
                    "candidate_sha": csha,
                    "expression": expr,
                    "family": fam,
                    "region": policy.region,
                    "universe": policy.universe,
                },
                payload_ref=cand_ref,
                actor=actor,
            )
            self.event_store.append(gen_e)
            graph.add_node(node_id=csha, node_type="candidate", payload_ref=cand_ref, event_id=gen_e.event_id)

            # 2. 生成 SimulationRequested Outbox 事件
            settings = {
                "region": policy.region,
                "universe": policy.universe,
                "delay": policy.delay,
            }
            ikey = compute_idempotency_key(policy.policy_id, csha, settings, "discovery_is")
            sim_req_e = Event.create(
                event_type=EventType.SIMULATION_REQUESTED,
                stream_id=stream_id,
                payload={
                    "candidate_sha": csha,
                    "idempotency_key": ikey,
                    "expression": expr,
                    "settings": settings,
                    "policy_id": policy.policy_id,
                },
                actor=actor,
            )
            self.event_store.append(sim_req_e)
            emitted_candidate_shas.append(csha)

        # 3. 触发 Outbox Worker 处理
        self.worker.process_pending_outbox(stream_id=stream_id)

        # 4. 同步更新物化视图
        all_events = self.event_store.read_stream(stream_id)
        self.projections.replay(all_events)

        return emitted_candidate_shas

    def compare_branches(
        self,
        branch_a_stream_id: str,
        branch_b_stream_id: str,
    ) -> Dict[str, Any]:
        """A/B 分支实验对比 (严格在相同数据分区与预算下比较策略效能)."""
        events_a = self.event_store.read_stream(branch_a_stream_id)
        events_b = self.event_store.read_stream(branch_b_stream_id)

        proj_a = ProjectionEngine()
        proj_a.replay(events_a)

        proj_b = ProjectionEngine()
        proj_b.replay(events_b)

        cands_a = list(proj_a.candidates.values())
        cands_b = list(proj_b.candidates.values())

        successful_a = [c for c in cands_a if c.sharpe >= 1.25 and c.fitness >= 1.0]
        successful_b = [c for c in cands_b if c.sharpe >= 1.25 and c.fitness >= 1.0]

        hit_rate_a = len(successful_a) / max(len(cands_a), 1)
        hit_rate_b = len(successful_b) / max(len(cands_b), 1)

        winner = "Branch_A" if hit_rate_a > hit_rate_b else ("Branch_B" if hit_rate_b > hit_rate_a else "Tie")

        return {
            "branch_a": {
                "total_candidates": len(cands_a),
                "successful_alphas": len(successful_a),
                "hit_rate": round(hit_rate_a, 4),
            },
            "branch_b": {
                "total_candidates": len(cands_b),
                "successful_alphas": len(successful_b),
                "hit_rate": round(hit_rate_b, 4),
            },
            "winner": winner,
            "conclusion": f"策略胜出方: {winner} (对比基准: 单位算力下的合格 Alpha 产出率)",
        }
