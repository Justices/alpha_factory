"""基于字段命名语义构造定向二元表达式。

规则刻意保守：只在同一数据集内匹配，避免把名称偶然相似的字段组合。
* ``positive`` / ``negative``：名称仅在该词上不同，构造正负差值。
* ``*_cap``：以 cap 字段为分母；仅匹配名称以前缀 ``<root>`` 开头的字段。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Tuple

from .families import Task
from .fields import DEFAULT_VEC_OPS, FieldSpec, preprocess_field


_POLARITY = re.compile(r"(?<![a-z0-9])(?:positive|negative)(?![a-z0-9])")


def _polarity_key(field_id: str) -> str:
    return _POLARITY.sub("{polarity}", field_id.lower())


def find_positive_negative_pairs(fields: Sequence[FieldSpec]) -> List[Tuple[FieldSpec, FieldSpec]]:
    """找出同数据集下名称对应的 ``positive`` / ``negative`` 字段对。"""
    positive: Dict[Tuple[str, str], FieldSpec] = {}
    negative: Dict[Tuple[str, str], FieldSpec] = {}
    for field in fields:
        lowered = field.id.lower()
        if field.type not in ("MATRIX", "VECTOR"):
            continue
        key = (field.dataset_id, _polarity_key(field.id))
        if re.search(r"(?<![a-z0-9])positive(?![a-z0-9])", lowered):
            positive[key] = field
        elif re.search(r"(?<![a-z0-9])negative(?![a-z0-9])", lowered):
            negative[key] = field
    return [(positive[key], negative[key]) for key in sorted(positive.keys() & negative.keys())]


def find_cap_pairs(fields: Sequence[FieldSpec]) -> List[Tuple[FieldSpec, FieldSpec]]:
    """找出同数据集、共享 ``*_cap`` 前缀的分子/分母字段对。

    例如 ``abc_revenue`` 与 ``abc_cap`` 匹配为 ``abc_revenue / abc_cap``。
    """
    pairs: List[Tuple[FieldSpec, FieldSpec]] = []
    scalar_fields = [f for f in fields if f.type in ("MATRIX", "VECTOR")]
    for denominator in scalar_fields:
        if not denominator.id.lower().endswith("_cap"):
            continue
        root = denominator.id[:-4].lower()
        prefix = f"{root}_"
        for numerator in scalar_fields:
            if numerator.id == denominator.id or numerator.dataset_id != denominator.dataset_id:
                continue
            if numerator.id.lower().startswith(prefix):
                pairs.append((numerator, denominator))
    return pairs


def semantic_pair_task_factory(
    fields: Sequence[FieldSpec],
    *,
    backfill: int = 120,
    winsorize_std: float = 4.0,
    vector_ops: Tuple[str, ...] = DEFAULT_VEC_OPS,
    decay: float = 6.0,
) -> List[Task]:
    """生成正负差值与 cap 归一化的定向二元任务。"""
    tasks: List[Task] = []
    seen = set()

    def expressions(field: FieldSpec) -> List[str]:
        return preprocess_field(
            field, backfill=backfill, winsorize_std=winsorize_std, vector_ops=vector_ops
        )

    for positive, negative in find_positive_negative_pairs(fields):
        for left, right in zip(expressions(positive), expressions(negative)):
            expression = f"({left} - {right})"
            if expression in seen:
                continue
            seen.add(expression)
            tasks.append(Task(
                expression=expression,
                template_index=-1001,
                family="semantic_pair",
                fields_per_alpha=2,
                decay=decay,
                base_fields=(positive.id, negative.id),
                meta={"label": "positive_minus_negative", "pair_type": "polarity"},
            ))

    for numerator, denominator in find_cap_pairs(fields):
        for left in expressions(numerator):
            for right in expressions(denominator):
                expression = f"({left} / ({right} + 0.000001))"
                if expression in seen:
                    continue
                seen.add(expression)
                tasks.append(Task(
                    expression=expression,
                    template_index=-1002,
                    family="semantic_pair",
                    fields_per_alpha=2,
                    decay=decay,
                    base_fields=(numerator.id, denominator.id),
                    meta={"label": "field_divided_by_cap", "pair_type": "cap_ratio"},
                ))
    return tasks


__all__ = [
    "find_positive_negative_pairs",
    "find_cap_pairs",
    "semantic_pair_task_factory",
]
