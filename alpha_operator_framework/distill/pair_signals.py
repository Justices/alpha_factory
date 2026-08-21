"""配对级信号蒸馏 — 研究闭环 P2 (相反/复合配对的信号沉淀, 第6→2 回流).

把带 pair_spec 元数据的回测结果按配对聚合出信号命中统计, 供下一轮优先复用
有信号的配对。与 field_signals (字段维度) 互补: 这里沉淀的是「配对关系」本身
(如 bullish-bearish 差值、raised-lowered 净比例) 是否有效。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List

from alpha_operator_framework.domain.density import SignalGate


@dataclass
class PairSignalStat:
    """单个配对 (pair_spec) 在某区域/股票池/轮次下的信号统计."""

    pair_spec: str          # "kind:left:right[:denominator]"
    pair_kind: str = ""     # difference / ratio / spread / net_revision
    region: str = ""
    universe: str = ""
    delay: int = 1
    round: int = 0
    trials: int = 0         # 该配对参与回测次数
    signal_count: int = 0   # 通过信号门次数
    hit_rate: float = 0.0
    avg_sharpe: float = 0.0
    max_sharpe: float = 0.0
    min_sharpe: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate_pair_signals(
    results: Iterable[Dict[str, Any]],
    *,
    region: str,
    universe: str = "",
    delay: int = 1,
    round_n: int = 0,
    gate: SignalGate = SignalGate(),
) -> List[PairSignalStat]:
    """按配对 (pair_spec) 聚合回测结果的信号统计.

    只统计带 ``pair_spec`` 元数据的行 (paired_base 任务回测结果), 其余行 (一阶/
    模板/语义配对) 忽略 —— 本函数专注「配对关系」维度的沉淀。

    Args:
        results: 回测结果行 (需含 pair_spec/pair_kind 元数据 + 指标)
        region/universe/delay/round_n: 沉淀维度
        gate: 信号门

    Returns:
        PairSignalStat 列表, 按 hit_rate → signal_count → avg_sharpe 降序
    """
    agg: Dict[str, Dict[str, Any]] = {}
    for row in results:
        pair_spec = row.get("pair_spec")
        if not pair_spec:
            continue
        ok, snap = gate.is_signal(row)
        sharpe = snap.get("sharpe")
        b = agg.setdefault(str(pair_spec), {
            "pair_kind": row.get("pair_kind") or "",
            "trials": 0, "signals": 0, "sharpes": [],
        })
        b["trials"] += 1
        if ok:
            b["signals"] += 1
        if isinstance(sharpe, (int, float)):
            b["sharpes"].append(float(sharpe))

    out: List[PairSignalStat] = []
    for pair_spec, b in agg.items():
        trials = b["trials"]
        signals = b["signals"]
        sharpes = b["sharpes"]
        out.append(PairSignalStat(
            pair_spec=pair_spec,
            pair_kind=b["pair_kind"],
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
        ))
    out.sort(key=lambda s: (s.hit_rate, s.signal_count, s.avg_sharpe), reverse=True)
    return out
