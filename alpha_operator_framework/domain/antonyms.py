"""相反词库驱动的字段配对发现.

把「相反指标配对」从硬编码规则升级为可扩展的相反词库:
  同 dataset 内, 名称只在相反词上不同的字段对 → 生成 ``difference`` 配对 (PairSpec),
  交给 ``paired_base_task_factory`` 生成经济二元基准信号。

设计:
  * ``DIFFERENCE_ANTONYMS`` 是简单相反词对表, 加一对即可扩展。
  * 归一化 key 复用 semantic_pairs 的占位符思路, 泛化到任意词对。
  * 与 semantic_pairs (positive/negative, cap) 和 paired_bases (raised/lowered, high/low)
    职责互补: 本模块只覆盖「简单差值类相反词」, 不重复已有机制。

刻意保守 (与 semantic_pairs 一致):
  * 只在同一 dataset 内匹配, 避免名称偶然相似的不同数据集字段被组合。
  * 字段同时含 a 和 b 时跳过 (避免自我配对)。
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.domain.paired_bases import (
    PairSpec,
    paired_base_task_factory,
)

# 简单相反词对 → difference 配对 (刻意排除已有机制覆盖的 positive/negative,
# raised/lowered, high/low, cap)
DIFFERENCE_ANTONYMS: Tuple[Tuple[str, str], ...] = (
    ("bullish", "bearish"),
    ("up", "down"),
    ("increase", "decrease"),
    ("inflow", "outflow"),
    ("gain", "loss"),
)

# long/short 是歧义最大的相反词: `long` 既可能是「多头」也可能是「长期」(long_term)。
# 只有「字段名以 _long/_short 结尾」的才是多头/空头配对; long_term/short_term/horizon
# 等时间修饰词被严格后缀规则天然排除。故不走通用词边界, 单独用后缀规则。
LONG_SHORT_SUFFIX: Tuple[str, str] = ("long", "short")
_LONG_SHORT_SUFFIX_RE = re.compile(r"_(long|short)$", re.IGNORECASE)


def _word_re(word: str) -> str:
    """词边界正则: 前后不能是字母数字 (下划线/空格/首尾均可作边界).

    lookaround 边界是关键: 它保证 `up` 不会命中 `group`/`sup` 里的子串,
    也不会命中 `upper` 这种前缀词 —— 只匹配「独立的相反词」。
    """
    return rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"


def _antonym_key(field_id: str, a: str, b: str) -> str:
    """把相反词 a/b 都替换成占位符 ``{antonym}``, 得到归一化 key.

    这是配对的核心技巧: `senti_bullish_flag` 和 `senti_bearish_flag` 归一化后
    都变成 `senti_{antonym}_flag`, key 相同 → 判定为同一对指标的相反两面。
    之所以用占位符替换而非直接字符串比较, 是因为相反词在字段名里的位置不固定
    (前缀/中缀/后缀都有), 只有归一化后才能对齐。
    """
    pat = re.compile(rf"{_word_re(a)}|{_word_re(b)}", re.IGNORECASE)
    return pat.sub("{antonym}", field_id.lower())


def _has_word(text: str, word: str) -> bool:
    return re.search(_word_re(word), text, re.IGNORECASE) is not None


def discover_antonym_pairs(
    fields: Sequence[FieldSpec],
    antonyms: Sequence[Tuple[str, str]] = DIFFERENCE_ANTONYMS,
) -> List[PairSpec]:
    """发现同 dataset 内、名称只在相反词上不同的字段对 (difference 语义).

    Args:
        fields: 字段规格列表
        antonyms: 相反词对序列 (默认 DIFFERENCE_ANTONYMS)

    Returns:
        PairSpec 列表 (kind=difference, source=antonym), 供 paired_base_task_factory 使用

    Example:
        >>> from alpha_operator_framework.domain.fields import FieldSpec
        >>> fields = [
        ...     FieldSpec(id="senti_bullish_flag", dataset_id="ds1", type="MATRIX"),
        ...     FieldSpec(id="senti_bearish_flag", dataset_id="ds1", type="MATRIX"),
        ... ]
        >>> pairs = discover_antonym_pairs(fields)
        >>> pairs[0].left, pairs[0].right
        ('senti_bullish_flag', 'senti_bearish_flag')
    """
    eligible = [f for f in fields if f.type in ("MATRIX", "VECTOR")]
    discovered: List[PairSpec] = []
    seen: set[tuple[str, str, str]] = set()

    for a, b in antonyms:
        # 两趟 bucket: 把「含 a 的字段」和「含 b 的字段」分别按归一化 key 归类。
        # 之后取 key 交集 = 同一对指标 (归一化后同名) 的相反两面, 天然完成配对。
        a_bucket: Dict[tuple[str, str], FieldSpec] = {}
        b_bucket: Dict[tuple[str, str], FieldSpec] = {}
        for field in eligible:
            lowered = field.id.lower()
            has_a = _has_word(lowered, a)
            has_b = _has_word(lowered, b)
            if has_a == has_b:
                # 都含 (如 inflow_outflow_ratio) 或都不含 → 跳过。
                # 都含时归一化后 key 带两个占位符, 无法对齐到纯 a/b 侧, 且会自我配对。
                continue
            # key 同时含 dataset_id, 保证只在同一数据集内配对 (跨数据集名称相似不配对)
            key = (field.dataset_id, _antonym_key(field.id, a, b))
            if has_a:
                a_bucket[key] = field
            else:
                b_bucket[key] = field

        for key in sorted(a_bucket.keys() & b_bucket.keys()):
            left, right = a_bucket[key], b_bucket[key]
            sig = (left.id, right.id, "difference")
            if sig in seen:
                continue  # 多词对可能撞到同一对字段 (防御性去重)
            seen.add(sig)
            discovered.append(PairSpec("difference", left.id, right.id, None, "antonym"))

    return discovered


def _long_short_key(field_id: str) -> str:
    """把结尾的 ``_long``/``_short`` 替换成占位符 ``_{antonym}``, 得到归一化 key."""
    return _LONG_SHORT_SUFFIX_RE.sub("_{antonym}", field_id.lower())


def discover_long_short_pairs(fields: Sequence[FieldSpec]) -> List[PairSpec]:
    """发现「多头/空头」字段对 (字段名以 _long/_short 结尾, 同 dataset 同 key).

    与 discover_antonym_pairs 的区别: 这里用严格后缀 ``_(long|short)$`` 而非词边界,
    以排除 long_term/short_term 等「长期/短期」时间修饰词 (它们不是相反配对)。
    后缀规则在真实字段上已验证: GBR/TOP700 发现 41 个干净的多头/空头配对。

    Args:
        fields: 字段规格列表

    Returns:
        PairSpec 列表 (kind=difference, source=long_short)
    """
    eligible = [f for f in fields if f.type in ("MATRIX", "VECTOR")]
    long_bucket: Dict[tuple[str, str], FieldSpec] = {}
    short_bucket: Dict[tuple[str, str], FieldSpec] = {}
    for field in eligible:
        m = _LONG_SHORT_SUFFIX_RE.search(field.id)
        if not m:
            continue
        side = m.group(1).lower()
        key = (field.dataset_id, _long_short_key(field.id))
        if side == "long":
            long_bucket[key] = field
        else:
            short_bucket[key] = field

    return [
        PairSpec("difference", long_bucket[k].id, short_bucket[k].id, None, "long_short")
        for k in sorted(long_bucket.keys() & short_bucket.keys())
    ]


def antonym_pair_tasks(
    fields: Sequence[FieldSpec],
    antonyms: Sequence[Tuple[str, str]] = DIFFERENCE_ANTONYMS,
    *,
    include_long_short: bool = True,
    backfill: int = 120,
    winsorize_std: float = 4.0,
    decay: float = 6.0,
):
    """便捷入口: 发现相反词配对 (通用词对 + long/short 后缀) 并生成基准信号任务.

    Args:
        fields: 字段规格列表
        antonyms: 通用相反词对 (默认 DIFFERENCE_ANTONYMS)
        include_long_short: 是否包含 long/short 后缀配对 (默认 True)
        backfill/winsorize_std/decay: 透传 paired_base_task_factory

    Returns:
        paired_base_task_factory 的 Task 列表 (family=paired_base)
    """
    specs = discover_antonym_pairs(fields, antonyms)
    if include_long_short:
        specs += discover_long_short_pairs(fields)
    if not specs:
        return []
    return paired_base_task_factory(
        specs, fields, backfill=backfill, winsorize_std=winsorize_std, decay=decay
    )


__all__ = [
    "DIFFERENCE_ANTONYMS",
    "LONG_SHORT_SUFFIX",
    "discover_antonym_pairs",
    "discover_long_short_pairs",
    "antonym_pair_tasks",
]
