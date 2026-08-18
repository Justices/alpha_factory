"""模板抽象器 — 研究闭环 P1 (第6步沉淀 → 回流第2步表达式合成).

把通过质量门的达标表达式反向抽象成可复用模板骨架:
字段 id → {a}/{b}/{c} 占位符, 算子/数字保留, 去重并按骨架信号密度 (support) 排序.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from alpha_operator_framework.domain.pruning import extract_fields
from alpha_operator_framework.database.models import Template

_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_SLOT_RE = re.compile(r"\{([a-z])\}")


@dataclass
class TemplateAbstraction:
    """从达标表达式抽象出的模板骨架."""

    expression_template: str
    source_fields: List[str] = field(default_factory=list)   # 抽象前字段 (按出现顺序)
    support: int = 0                                          # 相同骨架的达标表达式数
    source_expressions: List[str] = field(default_factory=list)  # 来源表达式

    def to_dict(self) -> dict:
        return asdict(self)


def abstract_template(expression: str, field_ids: Optional[Sequence[str]] = None) -> str:
    """把表达式里的底层字段替换成 {a}/{b}/{c} 占位符, 得到模板骨架.

    用 lookaround 边界匹配 (前后不能是字母数字下划线), 避免字段子串误伤
    (如 field "cap" 不会误替换 "market_cap" 里的 "cap").

    Args:
        expression: 渲染后的表达式
        field_ids: 显式字段顺序 (可选); 缺省按表达式内出现顺序 (长度降序)

    Returns:
        模板骨架字符串, 如 "ts_delta({a}, 5) + rank({b})"
    """
    if field_ids is None:
        field_ids = sorted(extract_fields(expression), key=len, reverse=True)
    else:
        field_ids = sorted((str(f) for f in field_ids), key=len, reverse=True)
    result = expression
    for i, fid in enumerate(field_ids):
        slot = "{" + _LETTERS[i] + "}"
        result = re.sub(
            r"(?<![A-Za-z0-9_])" + re.escape(str(fid)) + r"(?![A-Za-z0-9_])",
            slot,
            result,
        )
    return result


def abstract_templates(
    expressions: Iterable[str],
    *,
    min_support: int = 1,
) -> List[TemplateAbstraction]:
    """从一批达标表达式抽象模板骨架, 按 support 降序去重.

    Args:
        expressions: 达标表达式列表
        min_support: 最小支持度 (相同骨架至少出现几次才保留)

    Returns:
        TemplateAbstraction 列表 (按 support 降序)
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    for expr in expressions:
        expr = (expr or "").strip()
        if not expr:
            continue
        tpl = abstract_template(expr)
        if not tpl or tpl == expr:  # 没抽象出任何字段, 跳过
            continue
        b = buckets.setdefault(tpl, {"support": 0, "fields": [], "exprs": []})
        b["support"] += 1
        b["exprs"].append(expr)
        if not b["fields"]:
            b["fields"] = extract_fields(expr)
    out = [
        TemplateAbstraction(
            expression_template=tpl,
            source_fields=b["fields"],
            support=b["support"],
            source_expressions=b["exprs"],
        )
        for tpl, b in buckets.items()
        if b["support"] >= min_support
    ]
    out.sort(key=lambda t: t.support, reverse=True)
    return out


# ---------------------------------------------------------------------------
# 蒸馏回填 (P1: 抽象骨架 → template_library)
# ---------------------------------------------------------------------------

def to_template(
    abstraction: TemplateAbstraction,
    *,
    round_n: int = 0,
    family: str = "distilled",
) -> Template:
    """把一条 TemplateAbstraction 转成 template_library 的 Template 记录.

    骨架槽位 {a}/{b}/... 全部按标量槽 (type=data_field) 处理; 含 GROUP 字段的
    表达式在抽象时无法区分槽位类型, 本函数按纯标量建模 (P1 局限, 后续可扩展).

    Args:
        abstraction: 抽象结果
        round_n: 来源轮次 (可回放)
        family: 目标模板族 (默认 distilled, 不污染 4 族种子的密度统计)

    Returns:
        Template 记录; name = distilled_<sha12>, 幂等 (同骨架同名)
    """
    slots = list(dict.fromkeys(_SLOT_RE.findall(abstraction.expression_template)))
    placeholders = {s: {"role": "scalar", "type": "data_field"} for s in slots}
    digest = hashlib.sha256(abstraction.expression_template.encode("utf-8")).hexdigest()[:12]
    return Template(
        name=f"distilled_{digest}",
        title=f"蒸馏骨架 support={abstraction.support}",
        family=family,
        template_type="placeholder",
        expression_template=abstraction.expression_template,
        template_index=0,
        fields_per_alpha=len(abstraction.source_fields),
        expression_origin="distilled",
        field_types=["MATRIX", "VECTOR"],
        categories=[],
        dataset_families=[],
        placeholders=placeholders,
        group_slots=[],
        slot_count=len(slots),
        description="",
        rationale="从达标表达式自动抽象 (研究闭环沉淀)",
        example_expression=abstraction.source_expressions[0] if abstraction.source_expressions else "",
        operators_used=[],
        source={
            "type": "distilled",
            "round": round_n,
            "support": abstraction.support,
            "source_expressions": abstraction.source_expressions,
        },
        active=1,
    )


def distill_templates_into_library(
    db,
    expressions: Iterable[str],
    *,
    round_n: int = 0,
    min_support: int = 1,
    top_k: Optional[int] = None,
    family: str = "distilled",
) -> int:
    """把达标表达式抽象成模板骨架, 回填 template_library (研究闭环 第6→2 回流).

    Args:
        db: AlphaDatabase 实例
        expressions: 达标表达式列表 (如 deepen_kept 的 alpha 表达式)
        round_n: 研究轮次 (可回放)
        min_support: 骨架最小支持度 (相同骨架至少出现几次才回填)
        top_k: 只回填 support 最高的 top_k 条 (可选)
        family: 目标模板族 (默认 distilled)

    Returns:
        回填条数 (幂等: 同骨架重复蒸馏不重复插入)
    """
    abstractions = abstract_templates(expressions, min_support=min_support)
    if top_k is not None:
        abstractions = abstractions[:top_k]
    if not abstractions:
        return 0
    rows = [to_template(a, round_n=round_n, family=family) for a in abstractions]
    return db.upsert_templates(rows, overwrite=False)
