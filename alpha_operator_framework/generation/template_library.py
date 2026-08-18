"""模板类库 — 模板注册表与基于模板的创建策略.

职责:
  1. ``Template`` 记录: 模板表达式 / 模板类型(placeholder|fixed) / 字段类型限制 /
     适用 category / 模板说明, 与 knowledge_base/alpha_templates JSONL schema 对齐。
  2. 种子数据: 从 ``families.py`` 4 族常量构建 (``build_family_template_rows``),
     以及从知识库 JSONL 全量导入 (``import_knowledge_base_templates``)。
  3. 创建策略 (``template_creation_strategy``): 基于模板行生成 ``Task`` 列表,
     支持按模板 category / 字段类型限制过滤字段, 复用 families 的占位符渲染。

设计红线:
  * 纯函数 (不碰网络); 唯一收 db 的是 ``seed_template_library``。
  * 默认输出与 ``unary_factory/binary_factory/ternary_factory/quaternary_factory``
    字节级一致 (对 4 族种子行), 保证 survey 默认行为不变。
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from alpha_operator_framework.domain.families import (
    BINARY_TEMPLATES,
    QUATERNARY_TEMPLATES,
    TERNARY_TEMPLATES,
    UNARY_TEMPLATES,
    Task,
    _render,
)
from alpha_operator_framework.domain.fields import ScalarField
from alpha_operator_framework.database.models import Template


# ---------------------------------------------------------------------------
# 槽位提取 / 渲染
# ---------------------------------------------------------------------------

_SLOT_RE = re.compile(r"\{(\w+)\}|<([^>]+)>")


def extract_slot_names(expression: str) -> List[str]:
    """提取表达式里全部占位符名 ({a} / <name> 两种语法), 去重保序.

    同一占位符在表达式中出现多次 (如 ts_delta({a},252)/ts_delay({a},252))
    只计一次 —— 槽位映射到同一个字段。
    """
    names = [m.group(1) or m.group(2) for m in _SLOT_RE.finditer(expression or "")]
    return list(dict.fromkeys(names))


def _render_any(template: str, mapper: dict) -> str:
    """统一渲染: 先替换 <name> 语法, 再走 families._render 替换 {slot}.

    两种占位符语法并存: 4 族模板用 {a}/{b}, 知识库模板用 <company_fundamentals> 等。
    """
    for k, v in mapper.items():
        template = template.replace(f"<{k}>", str(v))
    return _render(template, mapper)


# ---------------------------------------------------------------------------
# 4 族种子数据
# ---------------------------------------------------------------------------

_FAMILY_META = {
    "unary":      {"field_types": ["MATRIX", "VECTOR"], "group_slots": [], "slot_count": 1, "origin": "unary_template"},
    "binary":     {"field_types": ["MATRIX", "VECTOR"], "group_slots": [], "slot_count": 2, "origin": ""},
    "ternary":    {"field_types": ["MATRIX", "VECTOR"], "group_slots": [], "slot_count": 3, "origin": ""},
    "quaternary": {"field_types": ["MATRIX", "VECTOR", "GROUP"], "group_slots": ["c"], "slot_count": 4, "origin": ""},
}

_FAMILY_TEMPLATES = {
    "unary": UNARY_TEMPLATES,
    "binary": BINARY_TEMPLATES,
    "ternary": TERNARY_TEMPLATES,
    "quaternary": QUATERNARY_TEMPLATES,
}

_SLOT_LABELS = {"a": "a", "b": "b", "c": "c", "d": "d"}


def build_family_template_rows() -> List[Template]:
    """从 families.py 4 族模板常量构建 30 行 Template 种子.

    Returns:
        Template 列表 (unary 10 / binary 8 / ternary 7 / quaternary 5)
    """
    rows: List[Template] = []
    for family, templates in _FAMILY_TEMPLATES.items():
        meta = _FAMILY_META[family]
        for idx, expression, rationale, fpa in templates:
            # 槽位元数据: 默认标量槽; quaternary 的 {c} 是 GROUP, {d} 是固定值 cap
            placeholders: Dict[str, Any] = {}
            for slot in meta["group_slots"]:
                placeholders[slot] = {"role": "group", "type": "grouping_data", "allowed_types": ["GROUP"]}
            for slot in extract_slot_names(expression):
                if slot in placeholders:
                    continue
                if slot == "d" and family == "quaternary":
                    placeholders[slot] = {"role": "fixed", "type": "data_field", "value": "cap"}
                else:
                    placeholders[slot] = {"role": "scalar", "type": "data_field"}
            rows.append(Template(
                name=f"{family}_{idx}",
                title=rationale,
                family=family,
                template_type="placeholder",
                expression_template=expression,
                template_index=idx,
                fields_per_alpha=fpa,
                expression_origin=meta["origin"],
                field_types=list(meta["field_types"]),
                categories=[],
                dataset_families=[],
                placeholders=placeholders,
                group_slots=list(meta["group_slots"]),
                slot_count=meta["slot_count"],
                description=rationale,
                rationale=rationale,
                source={"type": "families", "family": family},
                active=1,
            ))
    return rows


# ---------------------------------------------------------------------------
# 知识库 JSONL 导入
# ---------------------------------------------------------------------------

_KB_FAMILY = {
    "placeholder": "kb_placeholder",
    "factor": "kb_factor",
    "community": "kb_community",
    "cold": "kb_cold",
    "formulaic": "kb_formulaic",
}


def _kb_placeholders(raw: Any) -> Dict[str, Any]:
    """把知识库 placeholders dict 归一化 (槽位名 → {role, type, allowed_values, ...})."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            spec = {"description": str(spec)}
        ptype = spec.get("type", "data_field")
        out[str(name)] = {
            "role": "group" if ptype == "grouping_data" else ("scalar" if ptype == "data_field" else "enum"),
            "type": ptype,
            "allowed_values": spec.get("allowed_values"),
            "description": spec.get("description", ""),
            "constraints": spec.get("constraints", ""),
        }
    return out


def import_knowledge_base_templates(jsonl_path: str | Path, *, source_type: str) -> List[Template]:
    """从 knowledge_base/alpha_templates 的 JSONL 导入模板.

    Args:
        jsonl_path: JSONL 文件路径
        source_type: placeholder / factor / community / cold / formulaic

    Returns:
        Template 列表; family 带 kb_ 前缀, 默认不进 survey(按需启用)
    """
    family = _KB_FAMILY.get(source_type, f"kb_{source_type}")
    rows: List[Template] = []
    path = Path(jsonl_path)
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        expr = obj.get("expression_braint") or obj.get("expression_template") or obj.get("expression_raw") or ""
        if not expr:
            continue
        categories = obj.get("categories") or obj.get("category") or obj.get("dataset_category") or []
        if isinstance(categories, str):
            categories = [categories]
        rows.append(Template(
            name=f"kb_{source_type}_{obj.get('id')}",
            title=obj.get("title", ""),
            family=family,
            template_type="fixed" if (source_type == "formulaic" or obj.get("template_type") == "fixed") else "placeholder",
            expression_template=expr,
            template_index=0,
            fields_per_alpha=obj.get("fields_per_alpha", 0),
            expression_origin=obj.get("expression_origin", ""),
            field_types=obj.get("field_types", []),
            categories=[str(c) for c in categories],
            dataset_families=obj.get("dataset_families", []),
            placeholders=_kb_placeholders(obj.get("placeholders")),
            group_slots=[s for s, p in _kb_placeholders(obj.get("placeholders")).items() if p["role"] == "group"],
            slot_count=len(extract_slot_names(expr)),
            description=obj.get("applicable_conditions", ""),
            rationale=obj.get("idea") or obj.get("economic_rationale", ""),
            example_expression=obj.get("example_expression", ""),
            settings_hint=obj.get("settings_hint", {}),
            field_candidates=obj.get("field_candidates", {}),
            operators_used=obj.get("operators_used", []),
            source=obj.get("source", {}),
            active=1,
        ))
    return rows


# ---------------------------------------------------------------------------
# 创建策略
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemplateStrategyConfig:
    """基于模板库生成任务的策略配置."""

    families: Tuple[str, ...] = ("unary", "binary", "ternary", "quaternary")
    all_combinations: bool = True          # 与 survey --all-combinations 一致
    sample_n: int = 80                     # all_combinations=False 时每组组合上限
    decay: float = 6.0
    template_categories: Tuple[str, ...] = ()  # 限制"用哪些模板"; 空=任意模板


def _template_meta(tpl: Template, *, group: Optional[str] = None) -> Dict[str, Any]:
    meta = {"label": tpl.title or tpl.rationale, "window": 500, "source_freq": "unknown"}
    if tpl.categories:
        meta["template_categories"] = list(tpl.categories)
    if group is not None:
        meta["group"] = group
    return meta


def template_creation_strategy(
    templates: Sequence[Template],
    scalar_fields: Sequence[ScalarField],
    group_fields: Sequence[str],
    config: TemplateStrategyConfig = TemplateStrategyConfig(),
) -> List[Task]:
    """基于模板库生成 Task 列表 (创建策略).

    对每个模板行:
      - 按 family / active / template_categories 过滤
      - fixed 模板: 直接产出单个 Task
      - placeholder 模板: 槽位分类(标量/group/固定值) → 按模板 categories 过滤字段 →
        combinations 展开 → _render_any 渲染

    Args:
        templates: 模板库行
        scalar_fields: 已采样+预处理的标量(带 category)
        group_fields: GROUP 字段 id (供 group 槽位)
        config: 策略配置

    Returns:
        Task 列表; 对 4 族种子行与 factory 输出字节级一致
    """
    tasks: List[Task] = []
    cfg_categories = set(config.template_categories or ())

    for tpl in templates:
        if tpl.family not in config.families:
            continue
        if tpl.active != 1:
            continue
        if cfg_categories and tpl.categories and not (cfg_categories & set(tpl.categories)):
            continue

        # 1) fixed 模板直接产出
        if tpl.template_type == "fixed":
            tasks.append(Task(
                expression=tpl.expression_template,
                template_index=tpl.template_index,
                family=tpl.family,
                fields_per_alpha=tpl.fields_per_alpha,
                expression_origin=tpl.expression_origin,
                decay=config.decay,
                base_fields=(),
                meta=_template_meta(tpl),
            ))
            continue

        # 2) 槽位分类
        slots = extract_slot_names(tpl.expression_template)
        ph = tpl.placeholders or {}
        group_slot_set = set(tpl.group_slots or [])
        fixed_map: Dict[str, str] = {
            s: str(p["value"]) for s, p in ph.items()
            if p.get("role") == "fixed" and "value" in p
        }
        # 标量槽: 表达式中的非 group / 非 fixed 槽; 按字母序保证与 factory 的 {a}/{b}/{c} 映射一致
        scalar_slots = sorted(
            s for s in slots if s not in group_slot_set and s not in fixed_map
        )
        # 枚举槽 (operator/parameter, 知识库模板): 有 allowed_values 的
        enum_slots = [
            (s, list(p.get("allowed_values") or [])) for s, p in ph.items()
            if s in slots and p.get("role") == "enum" and p.get("allowed_values")
        ]
        group_slots = [s for s in slots if s in group_slot_set] or list(group_slot_set)

        # 3) 标量候选: 按模板 categories 过滤 (空=ALL)
        cand = [sf for sf in scalar_fields
                if (not tpl.categories) or (sf.category in tpl.categories)]
        if not cand and not enum_slots and not group_slots:
            continue  # 无可用字段且无枚举/group 槽, 跳过

        # 4) 组合展开
        combos: List[Tuple[ScalarField, ...]] = []
        if len(scalar_slots) == 1:
            combos = [(sf,) for sf in cand]
        elif len(scalar_slots) == 2:
            combos = list(itertools.combinations(cand, 2))
        elif len(scalar_slots) >= 3:
            combos = list(itertools.combinations(cand, len(scalar_slots)))
        if not config.all_combinations and combos:
            combos = combos[:config.sample_n]

        # 枚举槽值组合 (operator/parameter 笛卡尔积)
        enum_product = [dict(zip([s for s, _ in enum_slots], values))
                        for values in itertools.product(*[v for _, v in enum_slots])] if enum_slots else [{}]

        for combo in combos:
            mapper = {s: sf.expr for s, sf in zip(scalar_slots, combo)}
            mapper.update(fixed_map)
            base_fields = tuple(sf.expr for sf in combo)
            if group_slots:
                for g in group_fields:
                    for emap in enum_product:
                        g_mapper = {**mapper, **emap, group_slots[0]: g}
                        tasks.append(Task(
                            expression=_render_any(tpl.expression_template, g_mapper),
                            template_index=tpl.template_index,
                            family=tpl.family,
                            fields_per_alpha=tpl.fields_per_alpha,
                            expression_origin=tpl.expression_origin,
                            decay=config.decay,
                            base_fields=base_fields + (g,),
                            meta=_template_meta(tpl, group=g),
                        ))
            else:
                for emap in enum_product:
                    tasks.append(Task(
                        expression=_render_any(tpl.expression_template, {**mapper, **emap}),
                        template_index=tpl.template_index,
                        family=tpl.family,
                        fields_per_alpha=tpl.fields_per_alpha,
                        expression_origin=tpl.expression_origin,
                        decay=config.decay,
                        base_fields=base_fields,
                        meta=_template_meta(tpl),
                    ))

    return tasks


# ---------------------------------------------------------------------------
# 入库入口
# ---------------------------------------------------------------------------

def seed_template_library(db: Any, *, force: bool = False,
                          include_knowledge_base: bool = False,
                          knowledge_base_dir: Optional[str | Path] = None) -> int:
    """把模板种子写入 template_library 表 (幂等).

    Args:
        db: AlphaDatabase 实例
        force: True 时覆盖用户已有编辑 (upsert 全字段); False 保留已有 name
        include_knowledge_base: 是否同时导入知识库 JSONL (~210 行)
        knowledge_base_dir: 知识库目录; 缺省尝试默认路径

    Returns:
        写入/更新条数
    """
    rows = build_family_template_rows()
    if include_knowledge_base:
        kb_dir = Path(knowledge_base_dir) if knowledge_base_dir else (
            Path("..") / "ai" / "quant" / "knowledge_base" / "alpha_templates")
        for stype in _KB_FAMILY:
            rows.extend(import_knowledge_base_templates(
                kb_dir / f"{_KB_FILE[stype]}.jsonl", source_type=stype))
    return db.upsert_templates(rows, overwrite=force)


_KB_FILE = {
    "placeholder": "placeholder_alpha_templates",
    "factor": "factor_exposure_templates",
    "community": "community_templates",
    "cold": "cold_template_groups",
    "formulaic": "101_formulaic_alphas",
}


__all__ = [
    "Template",
    "TemplateStrategyConfig",
    "template_creation_strategy",
    "build_family_template_rows",
    "import_knowledge_base_templates",
    "seed_template_library",
    "extract_slot_names",
    "_render_any",
]
