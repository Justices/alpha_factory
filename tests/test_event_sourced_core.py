"""Unit tests for Event-Sourced Research Core (2026-08-21 Spec)."""

import pytest
import numpy as np

from alpha_operator_framework.core.artifacts import ArtifactStore
from alpha_operator_framework.core.engine import EventSourcedResearchEngine
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.core.outbox_worker import PlatformOutboxWorker, compute_idempotency_key
from alpha_operator_framework.core.policy import ResearchPolicy, StopPolicy
from alpha_operator_framework.core.projections import ProjectionEngine


def test_artifact_store_content_addressed(tmp_path):
    """测试不可变内容寻址工件库的存储与按 Hash 提取."""
    store = ArtifactStore(root_dir=tmp_path / "artifacts")

    # 1. 存储 JSON
    payload = {"strategy": "momentum", "decay": 12, "universe": "TOP700"}
    h_json = store.put_json(payload)
    assert len(h_json) == 64
    assert store.has(h_json)
    retrieved_json = store.get_json(h_json)
    assert retrieved_json == payload

    # 2. 存储纯文本表达式
    expr_text = "group_neutralize(rank(returns), subindustry)"
    h_text = store.put_text(expr_text)
    assert store.get_text(h_text) == expr_text


def test_event_store_append_and_read():
    """测试只追加事件流的写入、全局 Offset 与流式读取."""
    event_store = EventStore()

    e1 = Event.create(
        event_type=EventType.POLICY_CREATED,
        stream_id="stream_01",
        payload={"policy_name": "GBR_AltData"},
    )
    e2 = Event.create(
        event_type=EventType.CANDIDATE_GENERATED,
        stream_id="stream_01",
        payload={"expression": "rank(returns)"},
    )
    e3 = Event.create(
        event_type=EventType.CANDIDATE_GENERATED,
        stream_id="stream_02",
        payload={"expression": "rank(volume)"},
    )

    off1 = event_store.append(e1)
    off2 = event_store.append(e2)
    off3 = event_store.append(e3)

    assert off1 < off2 < off3

    # 读取 stream_01
    stream_1_events = event_store.read_stream("stream_01")
    assert len(stream_1_events) == 2
    assert stream_1_events[0].event_type == EventType.POLICY_CREATED
    assert stream_1_events[1].event_type == EventType.CANDIDATE_GENERATED

    # 全量读取
    all_evts = event_store.read_all()
    assert len(all_evts) == 3


def test_outbox_worker_idempotency():
    """测试 Outbox Worker 幂等执行，重复请求绝对不产生二次外部模拟."""
    event_store = EventStore()
    artifact_store = ArtifactStore()

    call_count = 0

    def mock_sim(expr, settings):
        nonlocal call_count
        call_count += 1
        return {
            "sharpe": 1.65,
            "fitness": 1.40,
            "turnover": 0.15,
            "returns": 0.20,
            "drawdown": 0.05,
            "evidence_level": "platform_is",
        }

    worker = PlatformOutboxWorker(event_store, artifact_store, simulator_fn=mock_sim)

    # 发送一个 SimulationRequested 事件
    ikey = compute_idempotency_key("pol_1", "cand_sha_01", {"region": "GBR"}, "discovery_is")
    req_evt = Event.create(
        event_type=EventType.SIMULATION_REQUESTED,
        stream_id="stream_idempotent",
        payload={
            "idempotency_key": ikey,
            "candidate_sha": "cand_sha_01",
            "expression": "rank(returns)",
            "settings": {"region": "GBR"},
        },
    )
    event_store.append(req_evt)

    # 第一次执行 worker
    res1 = worker.process_pending_outbox("stream_idempotent")
    assert len(res1) == 2  # Accepted + Completed
    assert call_count == 1

    # 第二次重复执行 worker (重试/崩溃恢复场景)
    res2 = worker.process_pending_outbox("stream_idempotent")
    assert len(res2) == 0  # 幂等跳过，无新增事件
    assert call_count == 1  # 外部模拟绝不重复调用！


def test_projections_100_percent_replayability():
    """测试从事件流完全重放重建只读物化视图 (Replay Consistency)."""
    engine = EventSourcedResearchEngine()
    policy = ResearchPolicy(policy_id="pol_replay_test")
    graph = engine.create_experiment(policy)

    candidates = [
        {"expression": "rank(returns) / rank(volume)", "family": "momentum"},
        {"expression": "ts_delta(returns, 10)", "family": "reversion"},
    ]

    engine.plan_and_simulate(graph, policy, candidates)

    # 获取当前物化视图状态
    initial_cands = dict(engine.projections.candidates)
    assert len(initial_cands) == 2

    # 创建一个全新的投影引擎，从 raw events 重放
    all_events = engine.event_store.read_stream(graph.graph_id)
    new_projections = ProjectionEngine()
    new_projections.replay(all_events)

    # 验证重放状态与实时状态 100% 严格一致
    assert len(new_projections.candidates) == len(initial_cands)
    for csha, cand in initial_cands.items():
        replayed_cand = new_projections.candidates[csha]
        assert replayed_cand.expression == cand.expression
        assert replayed_cand.sharpe == cand.sharpe
        assert replayed_cand.status == cand.status


def test_ab_branch_comparison():
    """测试 A/B 分支策略在严格相同的锁死数据与分区下的对照实验."""
    engine = EventSourcedResearchEngine()
    policy_a = ResearchPolicy(policy_id="policy_momentum_prior")
    policy_b = ResearchPolicy(policy_id="policy_reversion_prior")

    graph_a = engine.create_experiment(policy_a)
    graph_b = engine.create_experiment(policy_b)

    cands_a = [
        {"expression": "rank(returns)", "family": "ts_momentum"},
        {"expression": "ts_rank(returns, 22)", "family": "ts_momentum"},
    ]
    cands_b = [
        {"expression": "ts_delta(returns, 5)", "family": "mean_reversion"},
        {"expression": "reverse(rank(returns))", "family": "mean_reversion"},
    ]

    engine.plan_and_simulate(graph_a, policy_a, cands_a)
    engine.plan_and_simulate(graph_b, policy_b, cands_b)

    cmp_res = engine.compare_branches(graph_a.graph_id, graph_b.graph_id)

    assert "branch_a" in cmp_res
    assert "branch_b" in cmp_res
    assert "winner" in cmp_res
    assert cmp_res["branch_a"]["total_candidates"] == 2
    assert cmp_res["branch_b"]["total_candidates"] == 2
