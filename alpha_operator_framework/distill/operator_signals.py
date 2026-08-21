"""算子级信号蒸馏 — 研究闭环 (第6步沉淀 → 回流第2步表达式合成).

与 field_signals (字段级) 对应, 这里把回测结果按「算子」聚合信号命中统计,
供下一轮生成时**挑选**算子 (而非全量展开/随机抽样):
  - 有证据的算子: 按 hit_rate 降序优先入选
  - 零命中且样本充足的算子: 淘汰 (不再消耗回测额度)
  - 无统计的算子: 冷启动, 按 curated 白名单顺序兜底

纯函数 + 可回放 (带 round 维度), 不依赖网络。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from alpha_operator_framework.domain.density import SignalGate


@dataclass
class OperatorSignalStat:
    """单个算子在某区域/股票池/轮次下的信号统计."""

    operator: str
    region: str = ""
    universe: str = ""
    delay: int = 1
    round: int = 0
    trials: int = 0            # 含该算子的表达式回测次数
    signal_count: int = 0      # 通过信号门次数
    hit_rate: float = 0.0      # signal_count / trials
    avg_sharpe: float = 0.0
    max_sharpe: float = 0.0
    min_sharpe: float = 0.0
    avg_fitness: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# 函数调用名提取 (与 operators._FIRST_OP_RE 一致, 但这里要提取全部)
_OP_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# 内部结构算子 (预处理/分组包装), 不参与「挑选」语义 —— 它们是卫生层, 不是信号层
_STRUCTURAL_OPS = frozenset({
    "winsorize", "ts_backfill", "densify", "bucket", "reverse", "inverse",
})


def extract_operators(expression: str) -> List[str]:
    """提取表达式中出现的全部算子名 (去重, 保序).

    Example:
        >>> extract_operators("group_rank(ts_delta(close, 22), densify(sector))")
        ['group_rank', 'ts_delta']
    """
    if not expression:
        return []
    seen: dict[str, None] = {}
    for m in _OP_RE.finditer(expression):
        seen.setdefault(m.group(1), None)
    return [op for op in seen if op not in _STRUCTURAL_OPS]


def aggregate_operator_signals(
    results: Iterable[Dict[str, Any]],
    *,
    region: str,
    universe: str = "",
    delay: int = 1,
    round_n: int = 0,
    gate: SignalGate = SignalGate(),
) -> List[OperatorSignalStat]:
    """按算子聚合回测结果的信号统计.

    一次回测结果归因到表达式里用到的每个信号算子上 (与字段级统计同理)。

    Args:
        results: 回测结果行 (含 expression 及 sharpe/fitness 等指标)
        region: 区域
        universe: 股票池
        delay: 延迟
        round_n: 研究轮次
        gate: 信号门

    Returns:
        OperatorSignalStat 列表, 按 hit_rate → signal_count → avg_sharpe 降序
    """
    agg: Dict[str, Dict[str, Any]] = {}
    for row in results:
        ops = row.get("operators") or extract_operators(row.get("expression") or "")
        if not ops:
            continue
        ok, snap = gate.is_signal(row)
        sharpe = snap.get("sharpe")
        fitness = snap.get("fitness")
        for op in ops:
            op = str(op)
            b = agg.setdefault(op, {"trials": 0, "signals": 0, "sharpes": [], "fitnesses": []})
            b["trials"] += 1
            if ok:
                b["signals"] += 1
            if isinstance(sharpe, (int, float)):
                b["sharpes"].append(float(sharpe))
            if isinstance(fitness, (int, float)):
                b["fitnesses"].append(float(fitness))

    out: List[OperatorSignalStat] = []
    for op, b in agg.items():
        trials = b["trials"]
        signals = b["signals"]
        sharpes = b["sharpes"]
        fitnesses = b["fitnesses"]
        out.append(OperatorSignalStat(
            operator=op,
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


def select_curated_operators(
    db,
    *,
    default_ops: Sequence[str],
    region: str = "",
    universe: str = "",
    delay: int = 1,
    top_n: int = 8,
    min_trials: int = 3,
    cold_slots: int = 2,
) -> List[str]:
    """证据驱动的算子挑选 (替代全量展开/随机抽样).

    规则:
      1. 从 operator_signal_stats 取有统计的算子, hit_rate 降序
      2. trials >= min_trials 且 hit_rate = 0 的算子直接淘汰
      3. 有证据算子不足 top_n 时, 用 default_ops (curated 白名单) 按序补齐
      4. 保留 cold_slots 个「无统计」的冷启动名额, 保证探索不会停

    Args:
        db: AlphaDatabase 实例
        default_ops: 冷启动白名单 (顺序即优先级)
        region/universe/delay: 过滤统计维度
        top_n: 最终入选算子上限
        min_trials: 淘汰判定的最小样本数
        cold_slots: 留给无统计算子的探索名额

    Returns:
        挑选出的算子列表 (≤ top_n 个)
    """
    stats = db.get_operator_signal_stats(
        region=region or None, universe=universe or None, delay=delay, limit=500,
    ) if hasattr(db, "get_operator_signal_stats") else []
    by_op = {row.get("operator"): row for row in stats}

    picked: List[str] = []
    # 1) 有证据的算子按 hit_rate 降序入选 (同分按 avg_sharpe 绝对值, 负信号也有价值)
    evidenced = [
        row for row in stats
        if row.get("trials", 0) > 0 and row.get("hit_rate", 0.0) > 0.0
    ]
    for row in evidenced:
        op = row["operator"]
        if op not in picked:
            picked.append(op)
        if len(picked) >= top_n - cold_slots:
            break

    # 2) 白名单补齐 (跳过「样本充足但零命中」的已淘汰算子)
    for op in default_ops:
        if len(picked) >= top_n:
            break
        if op in picked:
            continue
        row = by_op.get(op)
        if row and row.get("trials", 0) >= min_trials and row.get("hit_rate", 0.0) <= 0.0:
            continue  # 零命中且样本充足 → 淘汰
        picked.append(op)
    return picked[:top_n]


__all__ = [
    "OperatorSignalStat",
    "extract_operators",
    "aggregate_operator_signals",
    "select_curated_operators",
]
