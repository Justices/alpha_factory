"""价值因子趋势与多样性得分计算器 (Value-Factor Diversity Score & Trend Engine).

理论依据:
  1. N: 评估窗口内提交的 Regular Alpha 总数
  2. A: ATOM (单数据集纯信号) Alpha 数量
  3. P: 覆盖的金字塔 (Pyramid) 类别数 (P_max 为平台最大金字塔类别数, 默认 10)
  4. S_A = A / N (单数据集纯度得分)
  5. S_P = P / P_max (金字塔覆盖广度得分)
  6. S_H: 金字塔分布的归一化香农信息熵 (衡量分布均衡度)
  7. Diversity Score = S_A * S_P * S_H
  8. 增量投影: Delta Diversity = Diversity_after - Diversity_before
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class ValueFactorDiversity:
    """价值因子多样性评估快照."""

    diversity_score: float              # 多样性总分 (0.0 ~ 1.0)
    N: int                              # 考察窗口内的 Regular Alpha 总量
    A: int                              # ATOM 单数据集纯信号总量
    P: int                              # 覆盖的金字塔主题数
    P_max: int                          # 金字塔总类别上限 (默认 10)
    S_A: float                          # 纯度比值 A / N
    S_P: float                          # 覆盖广度 P / P_max
    S_H: float                          # 归一化信息熵 (0.0 ~ 1.0)
    per_pyramid_counts: Dict[str, int] = field(default_factory=dict)


def is_atom_alpha(detail: Dict[str, Any]) -> bool:
    """判定 Alpha 是否属于 ATOM (单数据集纯信号) 属性."""
    if not isinstance(detail, dict):
        return False

    classifications = detail.get("classifications") or []
    has_classifications = len(classifications) > 0

    for cls in classifications:
        cid = str((cls or {}).get("id") or (cls or {}).get("name") or "")
        if "SINGLE_DATA_SET" in cid or "ATOM" in cid.upper():
            return True
        if "MULTI_DATA_SET" in cid:
            return False

    if has_classifications:
        return False

    # 检查 tags
    tags = detail.get("tags") or []
    for tag in tags:
        if isinstance(tag, str) and tag.strip().lower() == "atom":
            return True

    # 检查 fields 数据集数量 (如果用到的所有字段来自同一个 dataset 则为纯信号)
    fields_list = detail.get("fields") or []
    if isinstance(fields_list, list) and len(fields_list) > 0:
        datasets = {f.get("dataset_id") or f.get("dataset", {}).get("id") for f in fields_list if isinstance(f, dict)}
        datasets.discard(None)
        datasets.discard("")
        if len(datasets) <= 1:
            return True
        return False

    return True


def extract_pyramid_categories(detail: Dict[str, Any]) -> List[str]:
    """从 Alpha 详情中提取所属的数据金字塔分类名称."""
    if not isinstance(detail, dict):
        return []

    names: List[str] = []
    pyramids = detail.get("pyramids")
    if isinstance(pyramids, list):
        names.extend(p.get("name") for p in pyramids if isinstance(p, dict) and p.get("name"))

    themes = detail.get("pyramidThemes") or {}
    if isinstance(themes, dict):
        nested = themes.get("pyramids")
        if isinstance(nested, list):
            names.extend(p.get("name") for p in nested if isinstance(p, dict) and p.get("name"))

    # 如果平台未返回 pyramids 字段，从 category/dataset 中提取备用
    if not names:
        cat = detail.get("category") or detail.get("dataset_id") or "General"
        names.append(str(cat))

    return list(dict.fromkeys(names))


def _compute_normalized_entropy(per_pyramid: Dict[str, int]) -> float:
    """计算金字塔类别分布的归一化香农信息熵 (0.0 ~ 1.0)."""
    p = len(per_pyramid)
    if p <= 1:
        return 0.0

    total = sum(per_pyramid.values())
    if total <= 0:
        return 0.0

    entropy = 0.0
    for count in per_pyramid.values():
        if count > 0:
            prob = count / total
            entropy -= prob * math.log2(prob)

    max_entropy = math.log2(p)
    return float(entropy / max_entropy) if max_entropy > 0 else 0.0


def compute_value_factor_diversity(
    submitted_alphas: Sequence[Dict[str, Any]],
    max_pyramids: int = 10,
) -> ValueFactorDiversity:
    """根据已提交 Alpha 列表计算当前价值因子多样性得分快照."""
    n_total = len(submitted_alphas)
    if n_total == 0:
        return ValueFactorDiversity(
            diversity_score=0.0,
            N=0,
            A=0,
            P=0,
            P_max=max_pyramids,
            S_A=0.0,
            S_P=0.0,
            S_H=0.0,
            per_pyramid_counts={},
        )

    atom_count = sum(1 for a in submitted_alphas if is_atom_alpha(a))
    per_pyramid: Dict[str, int] = {}

    for a in submitted_alphas:
        cats = extract_pyramid_categories(a)
        for c in cats:
            per_pyramid[c] = per_pyramid.get(c, 0) + 1

    p_covered = len(per_pyramid)
    p_max = max(p_covered, max_pyramids)

    s_a = float(atom_count / n_total)
    s_p = float(p_covered / p_max)
    s_h = _compute_normalized_entropy(per_pyramid)
    diversity = float(s_a * s_p * s_h)

    return ValueFactorDiversity(
        diversity_score=round(diversity, 4),
        N=n_total,
        A=atom_count,
        P=p_covered,
        P_max=p_max,
        S_A=round(s_a, 4),
        S_P=round(s_p, 4),
        S_H=round(s_h, 4),
        per_pyramid_counts=per_pyramid,
    )


def project_diversity_after_submission(
    current: ValueFactorDiversity,
    candidate_detail: Dict[str, Any],
) -> Tuple[ValueFactorDiversity, float]:
    """推演若提交当前 candidate_detail，价值因子多样性得分的动态变化 (Delta Diversity).

    Returns:
        (projected_diversity, delta_diversity)
    """
    new_n = current.N + 1
    new_a = current.A + (1 if is_atom_alpha(candidate_detail) else 0)

    new_per_pyramid = dict(current.per_pyramid_counts)
    for cat in extract_pyramid_categories(candidate_detail):
        new_per_pyramid[cat] = new_per_pyramid.get(cat, 0) + 1

    new_p = len(new_per_pyramid)
    p_max = max(new_p, current.P_max)

    new_s_a = float(new_a / new_n)
    new_s_p = float(new_p / p_max)
    new_s_h = _compute_normalized_entropy(new_per_pyramid)
    new_diversity = float(new_s_a * new_s_p * new_s_h)

    delta = float(new_diversity - current.diversity_score)

    projected = ValueFactorDiversity(
        diversity_score=round(new_diversity, 4),
        N=new_n,
        A=new_a,
        P=new_p,
        P_max=p_max,
        S_A=round(new_s_a, 4),
        S_P=round(new_s_p, 4),
        S_H=round(new_s_h, 4),
        per_pyramid_counts=new_per_pyramid,
    )
    return projected, round(delta, 6)
