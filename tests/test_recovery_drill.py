"""End-to-End Small-Batch Crash Recovery Drill (小批崩溃恢复演练集成测试).

演练场景:
1. 策略初始化与时间分区锁死 (PartitionLocked)
2. 小批候选计划与 Outbox 请求 (SimulationRequested)
3. 平台接受仿真并记录 Location (SimulationAccepted)
4. 进程模拟崩溃中断 (Simulated Crash Before Completion)
5. 进程重启断点续传恢复 (Worker Outbox Resume & Complete)
6. 6 维提交证据终审与状态机流转 (DecisionApprovalEngine -> DecisionApproved/Rejected)
7. 持久化 TrialLedger 自由度累加校验
"""

import pytest
from pathlib import Path

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.engine import EventSourcedResearchEngine
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.core.policy import ResearchPolicy, ValidationPartitions
from alpha_operator_framework.domain.evidence import DecisionState, EvidenceLevel
from alpha_operator_framework.domain.overfitting import TrialLedger


def test_small_batch_recovery_drill(tmp_path):
    """执行完整的小批断点恢复与 6 维治理演练."""
    db_file = tmp_path / "drill_research.db"
    artifacts_dir = tmp_path / "artifacts"

    # --- Phase 1: 策略初始化与候选计划 ---
    event_store_1 = EventStore(db_path=str(db_file))
    artifact_store_1 = ArtifactStore(storage_dir=artifacts_dir)
    trial_ledger_1 = TrialLedger(db_path=str(db_file))

    call_count = 0

    def mock_platform_simulator(expr, settings):
        nonlocal call_count
        call_count += 1
        return {
            "alpha_id": f"REAL_ALPHA_{call_count:03d}",
            "expression": expr,
            "sharpe": 1.65,
            "fitness": 1.35,
            "turnover": 0.15,
            "margin": 6.5,
            "returns": 0.20,
            "drawdown": 0.06,
            "checks": [{"name": "LOW_SHARPE", "result": "PASS"}],
            "evidence_level": "platform_is",
        }

    engine_1 = EventSourcedResearchEngine(
        event_store=event_store_1,
        artifact_store=artifact_store_1,
        trial_ledger=trial_ledger_1,
        simulator_fn=mock_platform_simulator,
        production=True,
    )

    policy = ResearchPolicy(
        policy_id="pol_drill_001",
        region="GBR",
        universe="TOP700",
        validation=ValidationPartitions(
            discovery_is=["2016-01-01", "2021-12-31"],
            validation=["2022-01-01", "2023-12-31"],
            locked_oos=["2024-01-01", "2025-12-31"],
        ),
    )
    graph = engine_1.create_experiment(policy, graph_id="exp_drill_01")

    candidates = [
        {"expression": "ts_rank(returns, 22)", "family": "momentum"},
        {"expression": "reverse(rank(vwap))", "family": "mean_reversion"},
    ]

    # --- Phase 2: 模拟平台已接收 ACCEPTED，但进程在完成前发生崩溃 ---
    # 手动触发部分流程以模拟中断:
    emitted_shas = []
    for cand in candidates:
        expr = cand["expression"]
        fam = cand["family"]
        csha = EventSourcedResearchEngine.__module__  # just generate sha
        import hashlib
        csha = hashlib.sha256(expr.encode("utf-8")).hexdigest()
        emitted_shas.append(csha)

        trial_ledger_1.record_trial(expression=expr, family=fam, region="GBR", universe="TOP700")

        cand_ref = artifact_store_1.put_json(cand)
        gen_e = Event.create(
            event_type=EventType.CANDIDATE_GENERATED,
            stream_id=graph.graph_id,
            payload={"candidate_sha": csha, "expression": expr, "family": fam},
            payload_ref=cand_ref,
        )
        event_store_1.append(gen_e)

        from alpha_operator_framework.core.outbox_worker import compute_idempotency_key
        ikey = compute_idempotency_key(policy.policy_id, csha, {"region": "GBR"}, "discovery_is")

        # 写入 REQUESTED 与 ACCEPTED 事件
        req_e = Event.create(
            event_type=EventType.SIMULATION_REQUESTED,
            stream_id=graph.graph_id,
            payload={"candidate_sha": csha, "idempotency_key": ikey, "expression": expr, "settings": {"region": "GBR"}},
        )
        acc_e = Event.create(
            event_type=EventType.SIMULATION_ACCEPTED,
            stream_id=graph.graph_id,
            payload={"candidate_sha": csha, "idempotency_key": ikey, "platform_sim_id": f"sim_{csha[:8]}", "location": f"/simulations/sim_{csha[:8]}"},
        )
        event_store_1.append(req_e)
        event_store_1.append(acc_e)

    # 模拟 Crash: engine_1 实例退出
    del engine_1

    # --- Phase 3: 重启进程并断点恢复 ---
    event_store_2 = EventStore(db_path=str(db_file))
    artifact_store_2 = ArtifactStore(storage_dir=artifacts_dir)
    trial_ledger_2 = TrialLedger(db_path=str(db_file))

    engine_2 = EventSourcedResearchEngine(
        event_store=event_store_2,
        artifact_store=artifact_store_2,
        trial_ledger=trial_ledger_2,
        simulator_fn=mock_platform_simulator,
        production=True,
    )

    # 触发断点恢复
    recovered_events = engine_2.worker.process_pending_outbox("exp_drill_01")
    assert len(recovered_events) == 2  # 成功恢复并补齐 2 个 COMPLETED 事件
    assert all(e.event_type == EventType.SIMULATION_COMPLETED for e in recovered_events)
    assert call_count == 2

    # 重放物化视图
    engine_2.projections.replay(event_store_2.read_stream("exp_drill_01"))
    assert len(engine_2.projections.candidates) == 2

    first_sha = emitted_shas[0]
    cand_proj = engine_2.projections.candidates[first_sha]
    assert cand_proj.evidence_level == EvidenceLevel.PLATFORM_IS.value
    assert cand_proj.sharpe == 1.65

    # --- Phase 4: 6 维决策终审治理流转 ---
    # 模拟具备 Locked-OOS 补充证据
    oos_metrics = {"sharpe": 1.40}
    approval_rep = engine_2.advance_decision_governance(
        stream_id="exp_drill_01",
        candidate_sha=first_sha,
        oos_metrics=oos_metrics,
        judge_verdict="READY",
    )
    assert approval_rep.approved is True

    # 校验最终物化视图状态已更新为 SUBMISSION_READY
    events_final = event_store_2.read_stream("exp_drill_01")
    appr_events = [e for e in events_final if e.event_type == EventType.DECISION_APPROVED]
    assert len(appr_events) == 1
    assert appr_events[0].payload["decision_state"] == DecisionState.SUBMISSION_READY.value

    # 校验持久化试验账本
    assert trial_ledger_2._total_trials == 2
