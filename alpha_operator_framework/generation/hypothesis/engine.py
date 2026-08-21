"""假说驱动因子推理引擎 (Hypothesis-Driven Alpha Reasoning Engine).

功能:
  1. 将结构化金融假说实例化为具备强因果逻辑的 AST 任务
  2. 自动根据字段元数据 (Category/Description) 智能匹配假说插槽
  3. 提供与 LLM / AI Agent 交互的 Prompt 模版与响应解析
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from alpha_operator_framework.domain.ast import (
    canonicalize_expression,
    extract_ast_fields,
    to_canonical_string,
    validate_expression,
)
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.generation.hypothesis.taxonomy import (
    BUILTIN_HYPOTHESES,
    EconomicHypothesis,
    HypothesisCategory,
)


def _match_category_fields(field_specs: Sequence[FieldSpec]) -> Dict[str, List[str]]:
    """按语义分类归纳可用字段列表."""
    categorized: Dict[str, List[str]] = {
        "analyst": [],
        "price": [],
        "volume": [],
        "fundamental": [],
        "sentiment": [],
        "general": [],
    }

    for f in field_specs:
        fid = f.id
        desc = (f.description or "").lower()
        dset = (f.dataset_id or "").lower()
        cat = (f.category or "").lower()

        if any(k in fid or k in desc or k in dset for k in ("analyst", "est_", "rating", "target")):
            categorized["analyst"].append(fid)
        elif any(k in fid or k in desc for k in ("volume", "shares", "turnover", "trade")):
            categorized["volume"].append(fid)
        elif any(k in fid or k in desc for k in ("returns", "price", "vwap", "market_cap")):
            categorized["price"].append(fid)
        elif any(k in fid or k in desc or k in cat for k in ("cash", "earn", "income", "ebit", "revenue", "roe", "pe", "pb")):
            categorized["fundamental"].append(fid)
        elif any(k in fid or k in desc for k in ("sentiment", "news", "score", "social")):
            categorized["sentiment"].append(fid)
        else:
            categorized["general"].append(fid)

    return categorized


class HypothesisEngine:
    """假说驱动推理与任务生成器."""

    def __init__(self, hypotheses: Optional[Sequence[EconomicHypothesis]] = None):
        self.hypotheses = list(hypotheses or BUILTIN_HYPOTHESES)

    def instantiate_hypothesis(
        self,
        hypothesis: EconomicHypothesis,
        slot_assignment: Dict[str, str],
        decay: float = 6.0,
    ) -> List[Task]:
        """将指定的假说与字段槽位绑定，生成 AST 规范化后的任务列表.

        Args:
            hypothesis: 目标假说
            slot_assignment: 槽位字典，例如 {"a": "est_eps_up", "b": "est_eps_num"}
            decay: 默认衰减周期

        Returns:
            生成的 Task 任务列表
        """
        tasks: List[Task] = []
        base_fields = tuple(sorted(slot_assignment.values()))

        for idx, tpl in enumerate(hypothesis.templates):
            try:
                raw_expr = tpl.format(**slot_assignment)
                # 使用 AST 规范化化简
                can_expr = to_canonical_string(raw_expr)
                v_res = validate_expression(can_expr)
                if not v_res.is_valid:
                    continue

                task = Task(
                    expression=can_expr,
                    template_index=idx,
                    family="hypothesis",
                    fields_per_alpha=len(base_fields),
                    expression_origin=f"hyp_{hypothesis.category.value}",
                    decay=decay,
                    base_fields=base_fields,
                    meta={
                        "hypothesis_id": hypothesis.id,
                        "hypothesis_name": hypothesis.name,
                        "category": hypothesis.category.value,
                        "rationale": hypothesis.rationale,
                    },
                )
                tasks.append(task)
            except Exception:
                continue

        return tasks

    def generate_tasks_for_all_hypotheses(
        self,
        field_specs: Sequence[FieldSpec],
        max_tasks_per_hypothesis: int = 6,
    ) -> List[Task]:
        """根据当前可用字段池，自动推理匹配并生成所有假说的高质量任务."""
        categorized = _match_category_fields(field_specs)
        all_tasks: List[Task] = []

        for hyp in self.hypotheses:
            tasks_for_hyp: List[Task] = []

            # 根据假说类别挑选匹配字段对
            if hyp.category == HypothesisCategory.ANALYST_DISPERSION:
                candidates_a = categorized["analyst"] or categorized["general"]
                candidates_b = categorized["volume"] or categorized["price"] or categorized["general"]
            elif hyp.category == HypothesisCategory.LIQUIDITY_VOLATILITY:
                candidates_a = categorized["price"] or categorized["general"]
                candidates_b = categorized["volume"] or categorized["general"]
            elif hyp.category == HypothesisCategory.QUALITY_VALUE:
                candidates_a = categorized["fundamental"] or categorized["general"]
                candidates_b = categorized["fundamental"] or categorized["price"] or categorized["general"]
            elif hyp.category == HypothesisCategory.MOMENTUM_REVERSAL:
                candidates_a = categorized["price"] or categorized["general"]
                candidates_b = categorized["volume"] or categorized["price"] or categorized["general"]
            else:
                candidates_a = categorized["sentiment"] or categorized["general"]
                candidates_b = categorized["price"] or categorized["volume"] or categorized["general"]

            if not candidates_a:
                continue

            for fa in candidates_a[:3]:
                for fb in (candidates_b[:2] if candidates_b else [fa]):
                    if fa == fb and len(hyp.required_slots) > 1 and len(candidates_b) > 1:
                        continue
                    slots = {"a": fa, "b": fb, "c": fa}
                    gen = self.instantiate_hypothesis(hyp, slots)
                    tasks_for_hyp.extend(gen)
                    if len(tasks_for_hyp) >= max_tasks_per_hypothesis:
                        break
                if len(tasks_for_hyp) >= max_tasks_per_hypothesis:
                    break

            all_tasks.extend(tasks_for_hyp)

        return all_tasks

    def build_llm_prompt(
        self,
        market_region: str,
        universe: str,
        available_fields: Sequence[FieldSpec],
    ) -> str:
        """构建供 LLM / AI Agent 推理假说的结构化 Prompt."""
        fields_summary = [
            {"id": f.id, "type": f.type, "category": f.category, "description": f.description[:80]}
            for f in available_fields[:30]
        ]

        return (
            f"你是一个顶级量化对冲基金的资深研究员。我们正在对 {market_region} 市场 ({universe}) 进行因子挖掘。\n"
            f"以下是当前可用的一批关键数据字段：\n"
            f"{json.dumps(fields_summary, ensure_ascii=False, indent=2)}\n\n"
            f"请从金融经济学逻辑出发（如分析师预期漂移、流动性冲击、多空博弈、基本面错配），提出 1-3 个严谨的超额收益假说。\n"
            f"并针对每个假说，给出符合 WorldQuant BRAIN 语法（支持 rank, zscore, ts_rank, group_neutralize, ts_decay_linear 等）的具体公式表达式。\n"
            f"请以 JSON 格式输出：\n"
            f"[\n"
            f"  {{\n"
            f"    \"hypothesis_name\": \"假说名称\",\n"
            f"    \"rationale\": \"金融逻辑机理说明\",\n"
            f"    \"expression\": \"具体的表达式公式 (如 group_neutralize(ts_rank(close, 22), industry))\"\n"
            f"  }}\n"
            f"]\n"
        )
