"""因子密度评估器 — 继承 cold_templates 的核心方法论.

因子密度 = 该模板出信号的表达式占比, 是cold_templates方法论的灵魂:
  1. 先随机采样80组合
  2. 跑全部模板族
  3. 按模板聚合信号率
  4. 挑密度最大的几个模板深挖

信号门定义 (来自帖子评论区 39048053785623):
  - abs(sharpe)  > 0.7
  - abs(fitness) > 0.7
  - abs(pnl)     > 3_000_000
  - longCount + shortCount > 100

本模块不碰网络, 输入是模拟结果行列表, 输出密度报告。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence, List, Dict


# ---------------------------------------------------------------------------
# 信号门 — cold_templates 原貌
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalGate:
    """帖子信号定义. 任一不满足 → 非信号."""

    abs_sharpe_min: float = 0.7
    abs_fitness_min: float = 0.7
    abs_pnl_min: float = 3_000_000.0
    long_short_sum_min: int = 100

    def is_signal(self, row: dict) -> tuple[bool, dict]:
        """判断一行是否满足"信号". 返回 (是否信号, 指标快照)."""
        snap = {
            "sharpe": _metric(row, "sharpe"),
            "fitness": _metric(row, "fitness"),
            "pnl": _metric(row, "pnl"),
            "longCount": _metric(row, "longCount"),
            "shortCount": _metric(row, "shortCount"),
        }
        s, f, p, lc, sc = (snap["sharpe"], snap["fitness"], snap["pnl"],
                           snap["longCount"], snap["shortCount"])
        ok = (
            isinstance(s, (int, float)) and abs(s) > self.abs_sharpe_min
            and isinstance(f, (int, float)) and abs(f) > self.abs_fitness_min
            and isinstance(p, (int, float)) and abs(p) > self.abs_pnl_min
            and isinstance(lc, (int, float)) and isinstance(sc, (int, float))
            and (lc + sc) > self.long_short_sum_min
        )
        return ok, snap


# ---------------------------------------------------------------------------
# 密度统计
# ---------------------------------------------------------------------------

def _metric(row: dict, key: str) -> Any:
    """与 alpha_machine._metric 同语义: 顶层优先, 其次 is.* 子键."""
    if key in row:
        return row[key]
    is_block = row.get("is") or {}
    return is_block.get(key)


@dataclass
class DensityRow:
    """密度统计行."""

    template_index: int
    family: str
    source_freq: str = "unknown"
    sample_n: int = 0
    signal_n: int = 0
    mean_sharpe: float = 0.0
    median_sharpe: float = 0.0
    best_sharpe: float = 0.0
    fields_per_alpha: int = 0
    access_limited_n: int = 0
    density: float = 0.0  # = signal_n / sample_n (0..1)

    def to_dict(self) -> dict:
        return asdict(self)


def _denkey(row: dict) -> tuple[str, int, str]:
    """以 (family, template_index, source_freq) 为聚合key."""
    family = row.get("family") or row.get("template_family") or "unknown"
    raw_idx = row.get("template_index")
    if raw_idx is None:
        raw_idx = row.get("template_idx", -1)
    idx = int(raw_idx if raw_idx is not None else -1)
    src = (row.get("source_freq")
           or (row.get("meta") or {}).get("source_freq")
           or "unknown")
    return (family or "unknown", idx, src)


def compute_density(
    results: Iterable[dict],
    gate: SignalGate = SignalGate(),
    *,
    access_limited_ops: Sequence[str] = (),
) -> List[DensityRow]:
    """按模板key聚合每个key的因子密度.

    Args:
        results: 模拟结果行(带template_index/family元数据)
        gate: 信号门定义
        access_limited_ops: 受限算子列表(统计用)

    Returns:
        按density降序的DensityRow列表

    Example:
        >>> rows = compute_density(results, SignalGate())
        >>> rows[0].density  # 最高密度的模板
        0.15
    """
    buckets: Dict[tuple, List[dict]] = defaultdict(list)

    for row in results:
        # 跳过未跑出指标的pending行
        if row.get("status") == "PENDING_NEEDS_PAIR":
            continue
        buckets[_denkey(row)].append(row)

    rows: List[DensityRow] = []
    ops = tuple(access_limited_ops or ())

    for key, items in buckets.items():
        family, idx, src = key
        signals = 0
        sharpes: List[float] = []
        fpa = int(items[0].get("fields_per_alpha", 0) or 0)
        access_hit = 0

        for it in items:
            if ops and any(op in (it.get("expression") or "") for op in ops):
                access_hit += 1
            ok, snap = gate.is_signal(it)
            if ok:
                signals += 1
            sh = snap["sharpe"]
            if isinstance(sh, (int, float)):
                sharpes.append(float(sh))

        su = sorted(sharpes)
        n = len(items)
        mean_sh = sum(su) / len(su) if su else 0.0
        median_sh = su[len(su) // 2] if su else 0.0
        best_sh = su[-1] if su else 0.0
        density = (signals / n) if n else 0.0

        rows.append(DensityRow(
            template_index=idx,
            family=family,
            source_freq=src,
            sample_n=n,
            signal_n=signals,
            mean_sharpe=mean_sh,
            median_sharpe=median_sh,
            best_sharpe=best_sh,
            fields_per_alpha=fpa,
            access_limited_n=access_hit,
            density=density,
        ))

    # 主排序: density desc → sample_n desc → mean_sharpe desc
    rows.sort(key=lambda r: (r.density, r.sample_n, r.mean_sharpe), reverse=True)
    return rows


def top_templates(
    density_rows: List[DensityRow],
    *,
    top_n: int = 3,
    min_sample_n: int = 1
) -> List[DensityRow]:
    """取密度最高的top_n个key用于深挖.

    Args:
        density_rows: 密度行列表
        top_n: 取前N个
        min_sample_n: 最小样本数(防止小样本瞎中)

    Returns:
        Top-N密度行列表

    Example:
        >>> top3 = top_templates(rows, top_n=3)
        >>> [r.density for r in top3]
        [0.18, 0.15, 0.12]
    """
    eligible = [r for r in density_rows if r.sample_n >= min_sample_n]
    return eligible[:top_n] if top_n > 0 else eligible


# ---------------------------------------------------------------------------
# 报告 I/O
# ---------------------------------------------------------------------------

def write_report(
    density_rows: List[DensityRow],
    path: str | Path,
    *,
    gate: SignalGate = SignalGate(),
    top_n: int = 3,
    extra: dict | None = None
) -> Path:
    """写density报告(JSON).

    Args:
        density_rows: 密度行列表
        path: 输出路径
        gate: 信号门定义
        top_n: 取前N个用于深挖
        extra: 额外元数据

    Returns:
        输出路径

    Example:
        >>> write_report(rows, "density.json", top_n=3)
        PosixPath('density.json')
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    by_family: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"sample_n": 0, "signal_n": 0}
    )
    for r in density_rows:
        by_family[r.family]["sample_n"] += r.sample_n
        by_family[r.family]["signal_n"] += r.signal_n

    payload = {
        "gate": {
            "abs_sharpe_min": gate.abs_sharpe_min,
            "abs_fitness_min": gate.abs_fitness_min,
            "abs_pnl_min": gate.abs_pnl_min,
            "long_short_sum_min": gate.long_short_sum_min,
        },
        "summary": {
            "total_keys": len(density_rows),
            "by_family": {
                fam: {**v, "density": (v["signal_n"] / v["sample_n"]) if v["sample_n"] else 0.0}
                for fam, v in sorted(by_family.items())
            },
        },
        "top_for_deepen": [r.to_dict() for r in top_templates(density_rows, top_n=top_n)],
        "rows": [r.to_dict() for r in density_rows],
    }
    if extra:
        payload["extra"] = extra

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def read_report(path: str | Path) -> dict:
    """读density报告(JSON)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "SignalGate",
    "DensityRow",
    "compute_density",
    "top_templates",
    "write_report",
    "read_report",
]