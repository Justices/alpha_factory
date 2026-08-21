"""模板蒸馏淘汰 — 把低质量/零信号模板从可用集合里去掉.

两层淘汰机制:
  1. 模板级软删除 (deactivate_templates / deactivate_noisy_templates): 标记 template_library.active=0
  2. 表达式级规则匹配 (template_prune_rules): 存「表达式模式」, 在 survey 生成表达式时匹配过滤,
     能淘汰模式的所有变体 (不只固定模板)。

研究闭环第 6 步的「负向」管道, 与 ``distill_templates_into_library`` (正向沉淀好模板)
互补: 这里淘汰被回测验证零信号的坏模板/表达式, 让下一轮 survey 不再浪费回测预算。
"""

from __future__ import annotations

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
    if not targets:
        return []
    names = [t.name for t in targets]
    db.deactivate_templates(names=names)
    return names


def _template_to_pattern(expression_template: str) -> str:
    """把模板骨架转成前缀匹配模式: 截断到第一个占位符 ``{`` 之前.

    例如 ``ts_delta(ts_delta({a}, 252), 500)`` → ``ts_delta(ts_delta(``。
    这个前缀能匹配该模板的所有实例 (不管 {a} 被替换成什么字段表达式), 且天然
    把「增长率二阶」和「差分层叠」归并成同一条规则 (噪声本质相同)。
    """
    idx = expression_template.find("{")
    if idx <= 0:
        # 无占位符 (fixed 模板) → 用完整表达式做前缀
        return expression_template
    return expression_template[:idx]


def distill_prune_rules_from_density(
    db,
    density_rows: Sequence[Dict[str, Any]],
    *,
    min_density: float = 0.0,
    min_sample_n: int = 1,
) -> List[str]:
    """从回测密度数据自动生成淘汰规则 (淘汰规则自生长).

    对「被回测过 (sample_n >= min_sample_n) 但零信号 (density <= min_density)」的
    **模板库模板**, 提取其表达式骨架的算子前缀, 写入 template_prune_rules
    (source='distilled')。下一轮 survey 生成表达式时, 规则库匹配过滤这些模式的所有变体。

    与 prune_templates_by_density 的区别: 那个标记模板 active=0 (只淘汰固定模板),
    这个把模板骨架抽象成「模式」写入规则库 (淘汰所有变体, 且规则可跨族复用)。

    Args:
        db: AlphaDatabase 实例
        density_rows: compute_density 的输出行 (含 expression_origin/family/template_index/sample_n/density)
        min_density: 密度阈值, <= 此值视为低质量
        min_sample_n: 最小回测样本数, 低于此值视为「未充分采样」不淘汰

    Returns:
        写入的规则 pattern 列表
    """
    # 只处理模板库模板 (expression_origin != 'first_order' 排除一阶算子);
    # 否则一阶算子的 template_index 与模板库 index 混淆, 会误伤一阶算子。
    low_quality = {
        (str(r.get("family", "")), int(r.get("template_index", -1)))
        for r in density_rows
        if str(r.get("expression_origin") or "") != "first_order"
        and (r.get("sample_n") or 0) >= min_sample_n
        and (r.get("density") or 0.0) <= min_density
    }
    if not low_quality:
        return []

    # 匹配 template_library 的模板 (含已 active=0 的, 基于它们的骨架提取模式)
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


__all__ = [
    "deactivate_noisy_templates",
    "prune_templates_by_density",
    "DEFAULT_PRUNE_RULES",
    "matches_prune_rule",
    "prune_expression_candidates",
    "seed_default_prune_rules",
    "distill_prune_rules_from_density",
]
