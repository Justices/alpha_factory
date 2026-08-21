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
from alpha_operator_framework.domain import operators as _OPS
from alpha_operator_framework.domain.fields import ScalarField
from alpha_operator_framework.database.models import Template


# 算子分类 → 算子名列表 (供 operator 角色槽解析候选; 与 domain/operators 对齐)
_OPERATOR_CATEGORY_MAP = {
    "ts": _OPS.ts_ops,
    "group": _OPS.group_ops,
    "basic": _OPS.basic_ops,
    "vec": _OPS.vec_ops,
    "extended": _OPS.extended_ops,
}


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


def _enclosing_op(expression: str, pos: int) -> Optional[str]:
    """返回表达式里 ``pos`` 处最近的直接包裹算子名, 无则 None.

    从 ``pos`` 向左扫描, 找第一个**未配对**的 ``(`` (跳过已配对的括号层),
    取它前面的算子 token。用于判断一个 ``{slot}`` 是否被某个算子直接包裹
    (如 ``vec_count({a})`` 中 {a} 的直接包裹算子就是 vec_count)。
    """
    depth = 0
    for i in range(pos - 1, -1, -1):
        ch = expression[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                j = i - 1
                while j >= 0 and (expression[j].isalnum() or expression[j] == "_"):
                    j -= 1
                return expression[j + 1:i]
            depth -= 1
    return None


def slot_context_types(expression_template: str) -> Dict[str, str]:
    """识别模板表达式里每个 ``{slot}`` 的上下文类型.

    返回 {槽位名: "vector"|"scalar"}:
      - vector: 槽位被 ``vec_*`` 归约算子**直接包裹** (如 ``vec_count({a})``)。
        vec_* 只能作用于裸 VECTOR 字段 id, 所以该槽只能填「原始 VECTOR 字段」,
        绝不能填已预处理/已归约的标量表达式 —— 否则产生双重 vec 嵌套, 平台 ERROR。
      - scalar: 其它一切槽位, 填预处理后的标量表达式。

    这是「生成期不产生 vec 嵌套」的**源头约束依据**: 消费模板时按槽位类型
    过滤候选字段, 类型不匹配的组合直接不生成。

    Args:
        expression_template: 模板表达式 (含 {a}/{b} 占位符)

    Returns:
        槽位名 → 类型 的映射
    """
    types: Dict[str, str] = {}
    for m in _SLOT_RE.finditer(expression_template or ""):
        slot = m.group(1) or m.group(2)
        op = _enclosing_op(expression_template, m.start())
        types[slot] = "vector" if (op or "").startswith("vec_") else "scalar"
    return types


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
        # role 优先取显式声明, 否则按 type 推断
        role = spec.get("role")
        if role is None:
            role = "group" if ptype == "grouping_data" else ("scalar" if ptype == "data_field" else "enum")
        out[str(name)] = {
            "role": role,
            "type": ptype,
            "operator_category": spec.get("operator_category") if role == "operator" else None,
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


def _aggregate_operator_signals(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """把 operator_signal_stats 多行 (跨 round/维度) 聚合为 {operator: 累计 stat}.

    operator_signal_stats 用 UNIQUE(operator, region, universe, delay, round) 存多轮,
    这里累加 trials/signal_count 得到跨轮综合 hit_rate (avg/max sharpe 取最大)。
    """
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        op = r.get("operator")
        if not op:
            continue
        b = agg.setdefault(op, {"trials": 0, "signal_count": 0, "avg_sharpe": 0.0, "max_sharpe": 0.0})
        b["trials"] += int(r.get("trials", 0) or 0)
        b["signal_count"] += int(r.get("signal_count", 0) or 0)
        b["avg_sharpe"] = max(b["avg_sharpe"], float(r.get("avg_sharpe", 0.0) or 0.0))
        b["max_sharpe"] = max(b["max_sharpe"], float(r.get("max_sharpe", 0.0) or 0.0))
    for b in agg.values():
        b["hit_rate"] = (b["signal_count"] / b["trials"]) if b["trials"] else 0.0
    return agg


def _rank_operator_candidates(
    candidates: Sequence[str],
    signal_rows: Sequence[Dict[str, Any]],
    min_trials: int,
) -> List[str]:
    """按算子信号区分候选并排序 (不裁剪 —— 有信号 + 冷启动全部展开, 仅淘汰明确零命中者).

    规则:
      - 有信号 (hit_rate > 0): 全部展开, 按 hit_rate → signal_count → avg_sharpe 降序排前
      - 零命中且样本充足 (trials >= min_trials 且 hit_rate = 0): 淘汰 (不再消耗额度)
      - 无统计 / 样本不足: 冷启动兜底, 按原分类顺序跟在后 (探索不停)
    """
    sig = _aggregate_operator_signals(signal_rows)
    evidenced: List[str] = []
    cold: List[str] = []
    for op in candidates:
        st = sig.get(op)
        if not st:
            cold.append(op)
            continue
        if st["trials"] >= min_trials and st["hit_rate"] <= 0.0:
            continue  # 样本充足且零命中 → 淘汰
        if st["hit_rate"] > 0.0:
            evidenced.append(op)
        else:
            cold.append(op)  # 样本不足 (< min_trials), 不淘汰, 继续探索
    evidenced.sort(
        key=lambda op: (sig[op]["hit_rate"], sig[op]["signal_count"], sig[op]["avg_sharpe"]),
        reverse=True,
    )
    return evidenced + cold


def template_creation_strategy(
    templates: Sequence[Template],
    scalar_fields: Sequence[ScalarField],
    group_fields: Sequence[str],
    config: TemplateStrategyConfig = TemplateStrategyConfig(),
    vector_fields: Sequence[str] = (),
    operator_signals: Optional[Sequence[Dict[str, Any]]] = None,
    operator_min_trials: int = 3,
) -> List[Task]:
    """基于模板库生成 Task 列表 (创建策略).

    对每个模板行:
      - 按 family / active / template_categories 过滤
      - fixed 模板: 直接产出单个 Task
      - placeholder 模板: 槽位分类(标量/vector/group/固定值) → 按模板 categories
        过滤字段 → combinations 展开 → _render_any 渲染

    槽位类型约束 (生成期防 vec 嵌套的源头):
      - 被 ``vec_*`` 算子直接包裹的槽是 **vector 槽**, 只能填「裸 VECTOR 字段 id」。
        vec_* 归约只允许作用于原始 VECTOR 字段, 若填预处理标量表达式 (已含 vec_),
        会产生 vec_count(winsorize(ts_backfill(vec_sum(field)...))) 双重嵌套, 平台 ERROR。
      - 其它槽是 **scalar 槽**, 填预处理后的标量表达式。
      - 模板有 vector 槽但调用方未提供 vector_fields 候选 → 整个模板跳过,
        从源头保证「不生成 vec 嵌套的表达式」, 而不是生成后再过滤。

    Args:
        templates: 模板库行
        scalar_fields: 已采样+预处理的标量(带 category)
        group_fields: GROUP 字段 id (供 group 槽位)
        config: 策略配置
        vector_fields: 裸 VECTOR 字段 id 候选 (供 vector 槽); 空则跳过含 vector 槽的模板

    Returns:
        Task 列表; 对 4 族种子行与 factory 输出字节级一致
    """
    tasks: List[Task] = []
    cfg_categories = set(config.template_categories or ())
    vector_cands = list(vector_fields or ())

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
        # 上下文类型识别: 被 vec_* 直接包裹的槽是 vector 槽 (只能填裸 VECTOR 字段)。
        # 这是「生成期不产生 vec 嵌套」的关键: vector 槽绝不能被填入预处理标量表达式。
        ctx_types = slot_context_types(tpl.expression_template)
        vector_slots = sorted(s for s in slots if ctx_types.get(s) == "vector")
        # 算子槽 (operator 角色): 从算子分类 (domain/operators) 或 allowed_values 解析候选
        operator_slot_set = {
            s for s, p in ph.items()
            if s in slots and p.get("role") == "operator"
        }
        # 标量槽: 表达式中的非 group / 非 fixed / 非 vector / 非 operator 槽;
        # 按字母序保证与 factory 的 {a}/{b}/{c} 映射一致。operator 槽显式排除, 避免重蹈 enum 槽
        # 被错误塞进 scalar_slots 导致组合数多一维 + base_fields 混入无关字段的旧 bug。
        scalar_slots = sorted(
            s for s in slots
            if s not in group_slot_set and s not in fixed_map and s not in vector_slots and s not in operator_slot_set
        )
        # 枚举槽 (operator/parameter, 知识库模板): 有 allowed_values 的
        enum_slots = [
            (s, list(p.get("allowed_values") or [])) for s, p in ph.items()
            if s in slots and p.get("role") == "enum" and p.get("allowed_values")
        ]
        # 算子槽候选解析: 优先 allowed_values, 否则按 operator_category 取 domain/operators 分类全集
        # 若注入算子信号 (operator_signals), 按 hit_rate 区分: 有信号优先 + 零命中充足样本淘汰 + 冷启动兜底。
        operator_slots = []
        for s in operator_slot_set:
            p = ph.get(s, {})
            candidates = list(p.get("allowed_values") or [])
            if not candidates and p.get("operator_category") in _OPERATOR_CATEGORY_MAP:
                candidates = list(_OPERATOR_CATEGORY_MAP[p["operator_category"]])
            if not candidates:
                candidates = list(_OPS.ts_ops)  # 兜底
            if operator_signals:
                candidates = _rank_operator_candidates(candidates, operator_signals, operator_min_trials)
            operator_slots.append((s, candidates))
        group_slots = [s for s in slots if s in group_slot_set] or list(group_slot_set)

        # 3) 标量候选: 按模板 categories 过滤 (空=ALL)
        cand = [sf for sf in scalar_fields
                if (not tpl.categories) or (sf.category in tpl.categories)]
        if not cand and not enum_slots and not group_slots and not vector_slots:
            continue  # 无可用字段且无枚举/group/vector 槽, 跳过

        # vector 槽候选: 模板有 vector 槽但无 VECTOR 字段候选 → 跳过整个模板,
        # 保证 vec_ 算子永远只作用于裸 VECTOR 字段 (不产生双重 vec 嵌套)。
        if vector_slots and not vector_cands:
            continue

        # 4) 组合展开
        combos: List[Tuple[ScalarField, ...]] = []
        if not scalar_slots:
            combos = [()]
        elif len(scalar_slots) == 1:
            combos = [(sf,) for sf in cand]
        elif len(scalar_slots) == 2:
            combos = list(itertools.combinations(cand, 2))
        elif len(scalar_slots) >= 3:
            combos = list(itertools.combinations(cand, len(scalar_slots)))
        if not config.all_combinations and combos:
            combos = combos[:config.sample_n]

        # vector 槽组合: 裸 VECTOR 字段 id 的排列 (每个 vector 槽一个字段)
        vec_combos: List[Tuple[str, ...]] = [()]
        if vector_slots:
            if len(vector_slots) == 1:
                vec_combos = [(v,) for v in vector_cands]
            else:
                vec_combos = list(itertools.combinations(vector_cands, len(vector_slots)))

        # 枚举槽值组合 (operator/parameter 笛卡尔积)
        enum_product = [dict(zip([s for s, _ in enum_slots], values))
                        for values in itertools.product(*[v for _, v in enum_slots])] if enum_slots else [{}]
        # 算子槽组合 (operator 角色: ts/group 等分类笛卡尔积)
        operator_product = [dict(zip([s for s, _ in operator_slots], values))
                            for values in itertools.product(*[v for _, v in operator_slots])] if operator_slots else [{}]

        for combo in combos:
            mapper = {s: sf.expr for s, sf in zip(scalar_slots, combo)}
            mapper.update(fixed_map)
            base_fields = tuple(sf.expr for sf in combo)
            if group_slots:
                for g in group_fields:
                    for emap in enum_product:
                        for vcombo in vec_combos:
                            for omap in operator_product:
                                v_mapper = {**mapper, **emap, **dict(zip(vector_slots, vcombo))}
                                g_mapper = {**v_mapper, **omap, group_slots[0]: g}
                                tasks.append(Task(
                                    expression=_render_any(tpl.expression_template, g_mapper),
                                    template_index=tpl.template_index,
                                    family=tpl.family,
                                    fields_per_alpha=tpl.fields_per_alpha,
                                    expression_origin=tpl.expression_origin,
                                    decay=config.decay,
                                    base_fields=base_fields + tuple(vcombo) + (g,),
                                    meta=_template_meta(tpl, group=g),
                                ))
            else:
                for emap in enum_product:
                    for vcombo in vec_combos:
                        for omap in operator_product:
                            tasks.append(Task(
                                expression=_render_any(tpl.expression_template, {**mapper, **emap, **dict(zip(vector_slots, vcombo)), **omap}),
                                template_index=tpl.template_index,
                                family=tpl.family,
                                fields_per_alpha=tpl.fields_per_alpha,
                                expression_origin=tpl.expression_origin,
                                decay=config.decay,
                                base_fields=base_fields + tuple(vcombo),
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
    "slot_context_types",
    "_render_any",
]
