"""模板蒸馏淘汰 — 把低质量/零信号模板从可用集合里去掉.

两层淘汰机制:
  1. 模板级软删除 (deactivate_templates / deactivate_noisy_templates): 标记 template_library.active=0
  2. 表达式级规则匹配 (template_prune_rules): 存「表达式模式」, 在 survey 生成表达式时匹配过滤,
     能淘汰模式的所有变体 (不只固定模板)。

研究闭环第 6 步的「负向」管道, 与 ``distill_templates_into_library`` (正向沉淀好模板)
互补: 这里淘汰被回测验证零信号的坏模板/表达式, 让下一轮 survey 不再浪费回测预算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Sequence

# 已知噪声模板的表达式模式 (匹配 expression_template 前缀)
#   - 增长率二阶: ts_delta(ts_delta({a},252)/ts_delay({a},252), 252)   (UNARY_TEMPLATES idx=1)
#   - 差分层叠:   ts_delta(ts_delta({a},252), 500)                     (UNARY_TEMPLATES idx=9)
_NOISY_PREFIXES = (
    "ts_delta(ts_delta(",
)

# 默认淘汰规则 (表达式模式匹配): 每项 (pattern, pattern_type, family, reason)
# pattern_type: prefix(前缀) / substring(子串) / regex(正则)
DEFAULT_PRUNE_RULES: Sequence[Dict[str, str]] = (
    {
        "pattern": "ts_delta(ts_delta(",
        "pattern_type": "prefix",
        "family": "",
        "reason": "嵌套 ts_delta 二次差分放大噪声, 回测零信号",
    },
)


def matches_prune_rule(expression: str, rule: Dict[str, Any]) -> bool:
    """判断表达式是否命中一条淘汰规则 (pattern_type 决定匹配方式)."""
    pattern = str(rule.get("pattern", ""))
    ptype = str(rule.get("pattern_type", "prefix"))
    if not pattern:
        return False
    if ptype == "prefix":
        return expression.startswith(pattern)
    if ptype == "substring":
        return pattern in expression
    if ptype == "regex":
        return re.search(pattern, expression) is not None
    return False


def prune_expression_candidates(
    expressions: Sequence[str],
    rules: Sequence[Dict[str, Any]],
) -> List[str]:
    """过滤掉命中任一淘汰规则的表达式 (生成表达式时调用)."""
    if not rules:
        return list(expressions)
    return [
        e for e in expressions
        if not any(matches_prune_rule(e, r) for r in rules)
    ]


def seed_default_prune_rules(db) -> int:
    """把默认淘汰规则 (嵌套 ts_delta 等) 写入规则库, 返回写入/更新条数."""
    count = 0
    for rule in DEFAULT_PRUNE_RULES:
        rid = db.upsert_prune_rule(
            rule["pattern"],
            pattern_type=rule.get("pattern_type", "prefix"),
            family=rule.get("family", ""),
            reason=rule.get("reason", ""),
            source="static",
        )
        if rid > 0:
            count += 1
    return count


def deactivate_noisy_templates(db) -> List[str]:
    """静态淘汰已知噪声模板 (嵌套 ts_delta 的增长率二阶/差分层叠).

    Args:
        db: AlphaDatabase 实例 (template_library 表)

    Returns:
        被淘汰的模板 name 列表 (空=没有可淘汰的噪声模板)
    """
    templates = db.list_templates(active_only=True)
    noisy = [
        t for t in templates
        if t.expression_template.startswith(_NOISY_PREFIXES)
    ]
    if not noisy:
        return []
    names = [t.name for t in noisy]
    db.deactivate_templates(names=names)
    return names


def prune_templates_by_density(
    db,
    density_rows: Sequence[Dict[str, Any]],
    *,
    min_density: float = 0.0,
    min_sample_n: int = 1,
) -> List[str]:
    """基于回测密度数据淘汰低质量模板 (数据驱动).

    对「被回测过 (sample_n >= min_sample_n) 但零信号 (density <= min_density)」的模板,
    按 (family, template_index) 匹配 template_library 表并标记 active=False。

    Args:
        db: AlphaDatabase 实例
        density_rows: compute_density 的输出行 (含 family/template_index/sample_n/density)
        min_density: 密度阈值, <= 此值视为低质量
        min_sample_n: 最小回测样本数, 低于此值视为「未充分采样」不淘汰

    Returns:
        被淘汰的模板 name 列表

    Note:
        density 报告的 template_index 目前混了「一阶算子索引」与「模板库模板索引」
        两个体系 (都标记 family=unary), 对 unary 族可能有歧义。静态淘汰
        (deactivate_noisy_templates) 更可靠; 本函数适用于 template_index 语义明确的族
        (binary/ternary/quaternary)。
    """
    # 从密度行里筛出「低质量且被充分采样」的 (family, template_index) 集合
    low_quality = {
        (str(r.get("family", "")), int(r.get("template_index", -1)))
        for r in density_rows
        if (r.get("sample_n") or 0) >= min_sample_n
        and (r.get("density") or 0.0) <= min_density
    }
    if not low_quality:
        return []

    # 匹配 template_library 里对应的模板
    targets = [
        t for t in db.list_templates(active_only=True)
        if (t.family, t.template_index) in low_quality
    ]
    names = [t.name for t in targets]
    db.deactivate_templates(names=names)
    return names


def _template_to_pattern(expression_template: str) -> str:
    """把模板骨架转成前缀匹配模式: 截断到第一个占位符 ``{`` 之前."""
    idx = expression_template.find("{")
    if idx <= 0:
        return expression_template
    return expression_template[:idx]


def distill_prune_rules_from_density(
    db,
    density_rows: Sequence[Dict[str, Any]],
    *,
    min_density: float = 0.0,
    min_sample_n: int = 1,
) -> List[str]:
    """从回测密度数据自动生成淘汰规则 (淘汰规则自生长)."""
    low_quality = {
        (str(r.get("family", "")), int(r.get("template_index", -1)))
        for r in density_rows
        if str(r.get("expression_origin") or "") != "first_order"
        and (r.get("sample_n") or 0) >= min_sample_n
        and (r.get("density") or 0.0) <= min_density
    }
    if not low_quality:
        return []

    patterns = set()
    for t in db.list_templates(active_only=False):
        if (t.family, t.template_index) in low_quality:
            pat = _template_to_pattern(t.expression_template)
            if pat:
                patterns.add(pat)

    written: List[str] = []
    for pat in sorted(patterns):
        rid = db.upsert_prune_rule(
            pat, pattern_type="prefix",
            reason="回测 density=0 自动蒸馏淘汰",
            source="distilled",
        )
        if rid > 0:
            written.append(pat)
    return written


@dataclass
class ConsensusPruningResult:
    """二维共识剪枝执行结果."""
    pruned_patterns: List[str] = field(default_factory=list)
    deactivated_templates: List[str] = field(default_factory=list)
    immune_templates: List[str] = field(default_factory=list)
    audit_logs: List[str] = field(default_factory=list)


@dataclass
class FieldSignalProfile:
    """单特征字段在多算子族中的信号纯度画像."""
    field_id: str
    tier: str  # "Alpha" | "Neutral" | "Noise"
    max_sharpe: float
    avg_sharpe: float
    families_tested: List[str]
    total_tests: int
    is_noise: bool = False


def evaluate_and_prune_templates_2d(
    db,
    results: Sequence[Any],
    *,
    min_distinct_fields: int = 3,
    failure_rate_threshold: float = 0.80,
    max_avg_sharpe: float = 0.10,
    min_sample_n: int = 4,
) -> ConsensusPruningResult:
    """【二维正交解耦智能剪枝引擎】: 基于多字段共识判定与金牌豁免机制淘汰结构失效模板.

    核心原则:
      1. 多字段共识保底: 模板必须跨越 >= min_distinct_fields 个不同特征实测且全面失败，才可判定为结构缺陷；
      2. 金牌豁免盾 (Gold Shield Immunity): 只要模板在任一字段上产生过 Sharpe >= 1.0 或 Fitness >= 1.0，
         立即享有豁免保护，绝对不予剪枝；
      3. 结构与字段解耦: 严防因单一噪声字段拉低均值而误杀优质模板骨架。

    Args:
        db: AlphaDatabase 实例
        results: 回测结果列表 (PlatformAlphaResult 或 dict)
        min_distinct_fields: 判定模板缺陷所需的最小相异字段数 (默认: 3)
        failure_rate_threshold: 判定失效的最小失败比例 (默认: 80%)
        max_avg_sharpe: 判定失效的最大平均夏普门槛 (默认: 0.10)
        min_sample_n: 判定失效所需的最小总样本量 (默认: 4)

    Returns:
        ConsensusPruningResult: 包含淘汰模式、停用模板、豁免名单与审计日志
    """
    from collections import defaultdict
    from alpha_operator_framework.distill.template_abstractor import abstract_templates

    ret = ConsensusPruningResult()
    if not results:
        return ret

    # 1. 规范化回测条目提取 (expression, sharpe, fitness, turnover)
    records: List[Dict[str, Any]] = []
    for r in results:
        expr = getattr(r, "expression", "") or (r.get("expression") if isinstance(r, dict) else "")
        shp = float(getattr(r, "sharpe", 0.0) if hasattr(r, "sharpe") else (r.get("sharpe", 0.0) if isinstance(r, dict) else 0.0))
        fit = float(getattr(r, "fitness", 0.0) if hasattr(r, "fitness") else (r.get("fitness", 0.0) if isinstance(r, dict) else 0.0))
        fam = getattr(r, "family", "") or (r.get("family") if isinstance(r, dict) else "")
        if expr:
            records.append({
                "expression": expr,
                "sharpe": shp,
                "fitness": fit,
                "family": fam,
            })

    # 2. 按模板骨架 (Skeleton) 聚合回测结果
    skeleton_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    skeleton_fields: Dict[str, set] = defaultdict(set)
    skeleton_winners: Dict[str, bool] = defaultdict(bool)

    for item in records:
        expr = item["expression"]
        # 抽象为骨架
        skels = abstract_templates([expr])
        if skels:
            skel = skels[0].expression_template if hasattr(skels[0], "expression_template") else str(skels[0])
        else:
            skel = expr
        skeleton_groups[skel].append(item)

        # 提取字段
        fields_in_expr = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr))
        exclude = {
            "rank", "group_rank", "group_neutralize", "group_zscore", "group_scale",
            "ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev",
            "subindustry", "industry", "sector", "market", "cap", "winsorize", "ts_backfill",
            "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_stddev", "vec_range", "std",
            "a", "b", "c", "d", "group", "decay", "window", "w"
        }
        actual_fields = {f for f in fields_in_expr if f not in exclude and not f.isdigit()}
        skeleton_fields[skel].update(actual_fields)

        # 检查是否胜出 (Sharpe >= 1.0 或 Fitness >= 1.0)
        if item["sharpe"] >= 1.0 or item["fitness"] >= 1.0:
            skeleton_winners[skel] = True

    # 3. 逐骨架执行多字段共识评估
    for skel, group in skeleton_groups.items():
        # 金牌豁免校验
        if skeleton_winners[skel]:
            ret.immune_templates.append(skel)
            ret.audit_logs.append(f"🛡️ [豁免保护] 模板骨架 `{skel}` 曾产生高夏普胜出因子，享有剪枝豁免权")
            continue

        distinct_fields = skeleton_fields[skel]
        total_tests = len(group)
        sharpes = [g["sharpe"] for g in group]
        avg_sharpe = sum(sharpes) / total_tests if total_tests > 0 else 0.0

        # 统计失败次数 (Sharpe <= 0.10)
        failure_count = sum(1 for s in sharpes if s <= 0.10)
        failure_rate = failure_count / total_tests if total_tests > 0 else 0.0

        # 核心共识条件: 多字段充分采样 + 高失败率 + 低均值
        if len(distinct_fields) >= min_distinct_fields and total_tests >= min_sample_n:
            if failure_rate >= failure_rate_threshold and avg_sharpe <= max_avg_sharpe:
                pattern = _template_to_pattern(skel)
                reason = (
                    f"二维多字段共识淘汰: 跨 {len(distinct_fields)} 个特征实测 {total_tests} 次, "
                    f"失败率 {failure_rate:.0%}, 均值 Sharpe {avg_sharpe:.2f}"
                )
                
                # 写入剪枝规则库
                if db and hasattr(db, "upsert_prune_rule"):
                    try:
                        db.upsert_prune_rule(
                            pattern=pattern,
                            pattern_type="prefix",
                            family=group[0]["family"],
                            reason=reason,
                            source="consensus_pruning",
                        )
                    except Exception as e:
                        pass

                # 软删除 template_library 中的对应模板
                if db and hasattr(db, "deactivate_templates"):
                    try:
                        db.deactivate_templates(expression_like=f"{pattern}%")
                    except Exception:
                        pass

                ret.pruned_patterns.append(pattern)
                ret.deactivated_templates.append(skel)
                ret.audit_logs.append(f"🚫 [共识剪枝] 淘汰模式 `{pattern}`: {reason}")
        elif total_tests >= min_sample_n and len(distinct_fields) < min_distinct_fields:
            ret.audit_logs.append(
                f"ℹ️ [保留观察] 模板骨架 `{skel}` 测试 {total_tests} 次但仅涉及 {len(distinct_fields)} 个字段，"
                f"未达 {min_distinct_fields} 个不同特征的共识门槛，暂不予剪枝 (防止字段误杀)"
            )

    return ret


def analyze_field_signal_quality(
    results: Sequence[Any],
    *,
    min_distinct_families: int = 3,
) -> Dict[str, FieldSignalProfile]:
    """【特征字段信号纯度画像分析】: 跨算子族解耦评估字段的固有预测力与信噪比."""
    from collections import defaultdict
    field_records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    exclude = {
        "rank", "group_rank", "group_neutralize", "group_zscore", "group_scale",
        "ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev",
        "subindustry", "industry", "sector", "market", "cap", "winsorize", "ts_backfill",
        "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_stddev", "vec_range", "std",
        "a", "b", "c", "d", "group", "decay", "window", "w"
    }

    for r in results:
        expr = getattr(r, "expression", "") or (r.get("expression") if isinstance(r, dict) else "")
        shp = float(getattr(r, "sharpe", 0.0) if hasattr(r, "sharpe") else (r.get("sharpe", 0.0) if isinstance(r, dict) else 0.0))
        fam = getattr(r, "family", "") or (r.get("family") if isinstance(r, dict) else "")

        tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr))
        actual_fields = [t for t in tokens if t not in exclude and not t.isdigit()]

        for f in actual_fields:
            field_records[f].append({"sharpe": shp, "family": fam})

    profiles: Dict[str, FieldSignalProfile] = {}
    for f, recs in field_records.items():
        total_tests = len(recs)
        sharpes = [rec["sharpe"] for rec in recs]
        families = list({rec["family"] for rec in recs if rec["family"]})
        max_s = max(sharpes) if sharpes else -1.0
        avg_s = sum(sharpes) / total_tests if total_tests > 0 else 0.0

        # 分层判别
        if max_s >= 0.8:
            tier = "Alpha"
            is_noise = False
        elif len(families) >= min_distinct_families and max_s <= 0.0:
            tier = "Noise"
            is_noise = True
        else:
            tier = "Neutral"
            is_noise = False

        profiles[f] = FieldSignalProfile(
            field_id=f,
            tier=tier,
            max_sharpe=max_s,
            avg_sharpe=avg_s,
            families_tested=families,
            total_tests=total_tests,
            is_noise=is_noise,
        )

    return profiles


__all__ = [
    "ConsensusPruningResult",
    "FieldSignalProfile",
    "evaluate_and_prune_templates_2d",
    "analyze_field_signal_quality",
    "deactivate_noisy_templates",
    "prune_templates_by_density",
    "DEFAULT_PRUNE_RULES",
    "matches_prune_rule",
    "prune_expression_candidates",
    "seed_default_prune_rules",
    "distill_prune_rules_from_density",
]
