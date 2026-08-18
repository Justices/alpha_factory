"""字段级信号蒸馏 — 研究闭环 P0 (第6步沉淀 → 回流第1步字段选择).

把一批回测结果按字段聚合出"信号命中统计", 供下一轮字段加权采样使用,
实现"哪些字段真的出信号"的经验沉淀与回流。纯函数 + 可回放 (带 round 维度).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from alpha_operator_framework.domain.density import SignalGate
from alpha_operator_framework.domain.pruning import extract_fields


@dataclass
class FieldSignalStat:
    """单个字段在某区域/股票池/轮次下的信号统计."""

    field_id: str
    dataset_id: str = ""
    region: str = ""
    universe: str = ""
    delay: int = 1
    round: int = 0
    trials: int = 0            # 该字段参与回测次数
    signal_count: int = 0      # 通过信号门次数
    hit_rate: float = 0.0      # signal_count / trials
    avg_sharpe: float = 0.0
    max_sharpe: float = 0.0
    min_sharpe: float = 0.0
    avg_fitness: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate_field_signals(
    results: Iterable[Dict[str, Any]],
    *,
    region: str,
    universe: str = "",
    delay: int = 1,
    round_n: int = 0,
    dataset_map: Optional[Dict[str, str]] = None,
    gate: SignalGate = SignalGate(),
) -> List[FieldSignalStat]:
    """按字段聚合回测结果的信号统计.

    Args:
        results: 回测结果行. 每行需含 expression 及指标 (sharpe/fitness/pnl/longCount/shortCount,
            顶层或 is 子键均可, 与 SignalGate.is_signal 一致); 也可显式带 field_ids 列表,
            覆盖从 expression 提取的结果
        region: 区域
        universe: 股票池
        delay: 延迟
        round_n: 研究轮次 (可回放沉淀)
        dataset_map: field_id → dataset_id 映射 (可选, 回填 dataset 维度)
        gate: 信号门定义

    Returns:
        FieldSignalStat 列表, 按 hit_rate → signal_count → avg_sharpe 降序
    """
    agg: Dict[str, Dict[str, Any]] = {}
    for row in results:
        field_ids = row.get("field_ids") or extract_fields(row.get("expression") or "")
        if not field_ids:
            continue
        ok, snap = gate.is_signal(row)
        sharpe = snap.get("sharpe")
        fitness = snap.get("fitness")
        for fid in field_ids:
            fid = str(fid)
            b = agg.setdefault(fid, {"trials": 0, "signals": 0, "sharpes": [], "fitnesses": []})
            b["trials"] += 1
            if ok:
                b["signals"] += 1
            if isinstance(sharpe, (int, float)):
                b["sharpes"].append(float(sharpe))
            if isinstance(fitness, (int, float)):
                b["fitnesses"].append(float(fitness))

    out: List[FieldSignalStat] = []
    for fid, b in agg.items():
        trials = b["trials"]
        signals = b["signals"]
        sharpes = b["sharpes"]
        fitnesses = b["fitnesses"]
        out.append(FieldSignalStat(
            field_id=fid,
            dataset_id=(dataset_map or {}).get(fid, ""),
            region=region,
            universe=universe,
            delay=delay,
            round=round_n,
            trials=trials,
            signal_count=signals,
            hit_rate=(signals / trials) if trials else 0.0,
            avg_sharpe=(sum(sharpes) / len(sharpes)) if sharpes else 0.0,
            max_sharpe=max(sharpes) if sharpes else 0.0,
            min_sharpe=min(sharpes) if sharpes else 0.0,
            avg_fitness=(sum(fitnesses) / len(fitnesses)) if fitnesses else 0.0,
        ))
    out.sort(key=lambda s: (s.hit_rate, s.signal_count, s.avg_sharpe), reverse=True)
    return out


def weighted_field_sample(
    stats: Sequence[FieldSignalStat],
    *,
    sample_n: int,
    min_trials: int = 1,
    cold_boost: float = 0.5,
    seed: Optional[int] = None,
) -> List[str]:
    """按信号命中率加权采样字段 (P0 回流: 上一轮有信号的字段更可能再次入选).

    权重 = max(0, hit_rate) + cold_boost; cold_boost 保证 hit_rate=0 的字段
    不会完全丧失机会 (冷启动探索). 无放回采样.

    Args:
        stats: aggregate_field_signals 的输出
        sample_n: 采样数量
        min_trials: 最小回测次数 (过滤噪声字段)
        cold_boost: 冷启动权重
        seed: 随机种子 (可复现)

    Returns:
        采样出的 field_id 列表
    """
    rng = random.Random(seed)
    pool = [s for s in stats if s.trials >= min_trials]
    if not pool:
        return []
    weights = [max(0.0, s.hit_rate) + cold_boost for s in pool]
    fields = [s.field_id for s in pool]
    n = min(sample_n, len(pool))
    picked: List[str] = []
    seen: set = set()
    while len(picked) < n:
        total = sum(w for i, w in enumerate(weights) if fields[i] not in seen)
        if total <= 0:
            break
        r = rng.uniform(0, total)
        acc = 0.0
        chosen: Optional[int] = None
        for i, f in enumerate(fields):
            if f in seen:
                continue
            acc += weights[i]
            if r <= acc:
                chosen = i
                break
        if chosen is None:
            for i, f in enumerate(fields):
                if f not in seen:
                    chosen = i
                    break
        if chosen is None:
            break
        seen.add(fields[chosen])
        picked.append(fields[chosen])
    return picked
