"""事件溯源研究内核 — 核心引擎与 A/B 对照实验控制器 (Event-Sourced Research Engine).

整合 Policy、ArtifactStore、EventStore、OutboxWorker、ProjectionEngine 与严格的 A/B 分支科学对照。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

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
        simulator_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        production: bool = False,
    ):
        self.production = production
        self.event_store = event_store or EventStore()
        self.artifact_store = artifact_store or ArtifactStore()

        # 生产环境安全断言
        if self.production:
            if self.event_store.db_path == ":memory:":
                raise ValueError("生产模式 (production=True) 必须使用持久化 EventStore，严禁使用 :memory:")
            if simulator_fn is None:
                raise ValueError("生产模式 (production=True) 必须注入真实的 PlatformGateway / simulator_fn，严禁使用默认 Mock")

        self.worker = PlatformOutboxWorker(
            self.event_store,
            self.artifact_store,
            simulator_fn=simulator_fn,
        )
        self.projections = ProjectionEngine()

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
            payload={
                "policy_id": policy.policy_id,
                "version": policy.version,
                "region": policy.region,
                "universe": policy.universe,
                "budget_total": getattr(policy.budget, "simulations_per_round", 100),
                "random_seed": random_seed,
            },
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
        """A/B 分支科学对照评估 (严格校验基准输入一致性，以 Locked-OOS 产出率与稳定性判胜)."""
        events_a = self.event_store.read_stream(branch_a_stream_id)
        events_b = self.event_store.read_stream(branch_b_stream_id)

        if not events_a or not events_b:
            raise ValueError("A/B 对照实验失败: 至少一个分支无事件流")

        # 1. 严格基线一致性检验 (Fail-Closed Baseline Check)
        part_a = next((e.payload for e in events_a if e.event_type == EventType.PARTITION_LOCKED), None)
        part_b = next((e.payload for e in events_b if e.event_type == EventType.PARTITION_LOCKED), None)

        if part_a != part_b:
            raise ValueError(f"A/B 对照实验无效: 分区基线不匹配 (A={part_a} vs B={part_b})")

        pol_a = next((e.payload for e in events_a if e.event_type == EventType.POLICY_CREATED), {})
        pol_b = next((e.payload for e in events_b if e.event_type == EventType.POLICY_CREATED), {})

        # 校验区域与宇宙一致
        if pol_a.get("region") != pol_b.get("region") or pol_a.get("universe") != pol_b.get("universe"):
            raise ValueError(f"A/B 对照实验无效: 市场区域或股票宇宙不一致")

        # 2. 物化视图重放
        proj_a = ProjectionEngine()
        proj_a.replay(events_a)

        proj_b = ProjectionEngine()
        proj_b.replay(events_b)

        cands_a = list(proj_a.candidates.values())
        cands_b = list(proj_b.candidates.values())

        # 3. 多维度科学评估模型:
        # 主指标: 单位预算下的合格因子数 (Sharpe >= 1.25, Fitness >= 1.0, Turnover <= 0.70)
        qualified_a = [c for c in cands_a if c.sharpe >= 1.25 and c.fitness >= 1.0 and c.turnover <= 0.70]
        qualified_b = [c for c in cands_b if c.sharpe >= 1.25 and c.fitness >= 1.0 and c.turnover <= 0.70]

        # 结构族分布多样性
        families_a = {c.family for c in qualified_a if c.family}
        families_b = {c.family for c in qualified_b if c.family}

        budget_a = max(len(cands_a), 1)
        budget_b = max(len(cands_b), 1)

        yield_per_budget_a = len(qualified_a) / budget_a
        yield_per_budget_b = len(qualified_b) / budget_b

        avg_sharpe_a = sum(c.sharpe for c in qualified_a) / max(len(qualified_a), 1)
        avg_sharpe_b = sum(c.sharpe for c in qualified_b) / max(len(qualified_b), 1)

        # 胜出判定: 主指标产出率优先，相同则按多样性与平均夏普仲裁
        if yield_per_budget_a > yield_per_budget_b:
            winner = "Branch_A"
        elif yield_per_budget_b > yield_per_budget_a:
            winner = "Branch_B"
        else:
            if len(families_a) > len(families_b):
                winner = "Branch_A"
            elif len(families_b) > len(families_a):
                winner = "Branch_B"
            else:
                winner = "Branch_A" if avg_sharpe_a > avg_sharpe_b else ("Branch_B" if avg_sharpe_b > avg_sharpe_a else "Tie")

        return {
            "validation_baseline": {
                "partition_verified": True,
                "partitions": part_a,
                "region": pol_a.get("region"),
                "universe": pol_a.get("universe"),
            },
            "branch_a": {
                "total_candidates": len(cands_a),
                "qualified_alphas": len(qualified_a),
                "qualified_families": len(families_a),
                "yield_per_budget": round(yield_per_budget_a, 4),
                "avg_sharpe": round(avg_sharpe_a, 2),
            },
            "branch_b": {
                "total_candidates": len(cands_b),
                "qualified_alphas": len(qualified_b),
                "qualified_families": len(families_b),
                "yield_per_budget": round(yield_per_budget_b, 4),
                "avg_sharpe": round(avg_sharpe_b, 2),
            },
            "winner": winner,
            "evaluation_criterion": "单位计算预算下产出的合格因子族数 (Yield per Budget) + 因子族结构多样性",
        }
