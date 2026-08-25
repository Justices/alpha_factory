"""Winning-template distillation stage for carpet mining."""

from __future__ import annotations

import logging
from typing import List

from alpha_operator_framework.distill.template_abstractor import abstract_templates
from alpha_operator_framework.domain.judge.evaluator import JudgeReport

logger = logging.getLogger(__name__)


def distill_and_persist_winning_templates(
    miner,
    final_reports: List[JudgeReport],
) -> List[str]:
    """从回测终审胜出的高分 Alpha 中反向抽象骨架，并自动沉淀至 template_library 知识库."""
    winning_exprs: List[str] = []
    for rep in final_reports:
        m = rep.metrics if hasattr(rep, "metrics") and rep.metrics else {}
        sharpe = float(m.get("sharpe") or (getattr(m, "sharpe", 0.0) if hasattr(m, "sharpe") else 0.0) or 0.0)
        verdict_str = str(rep.verdict.value if hasattr(rep.verdict, "value") else rep.verdict)
        if sharpe >= 1.0 or rep.priority_score >= 60.0 or verdict_str == "ACCEPTED":
            if rep.expression and rep.expression not in winning_exprs:
                winning_exprs.append(rep.expression)

    if not winning_exprs:
        logger.info("本轮未发现达到蒸馏门槛 (Sharpe>=1.0) 的胜出 Alpha，跳过模板抽象")
        return []

    # 执行反向语法骨架抽象
    abstractions = abstract_templates(winning_exprs, min_support=1)
    distilled_skeletons: List[str] = []

    if miner.db and hasattr(miner.db, "save_abstracted_template"):
        for abs_tpl in abstractions:
            saved = miner.db.save_abstracted_template(
                expression_template=abs_tpl.expression_template,
                family="evolved_distillation",
                title="自主进化高阶模板",
                description=f"由地毯式挖掘胜出因子自动蒸馏生成 (支撑度: {abs_tpl.support})",
                support_count=abs_tpl.support,
                source="autonomous_distillation",
                example_expression=abs_tpl.source_expressions[0] if abs_tpl.source_expressions else "",
            )
            if saved:
                distilled_skeletons.append(abs_tpl.expression_template)

    if distilled_skeletons:
        print(f"\n✨ [知识沉淀] 成功从本轮胜出因子中自主反向蒸馏出 {len(distilled_skeletons)} 个高阶模板并写入知识库:")
        for idx, skel in enumerate(distilled_skeletons[:5], 1):
            print(f"   {idx}. `{skel}`")

    return distilled_skeletons



__all__ = ["distill_and_persist_winning_templates"]

