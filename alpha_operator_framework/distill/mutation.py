"""针对性 AST 基因突变与自动修复引擎 (Alpha Auto-Mutation Engine).

功能:
  1. 根据 FailureDiagnosis 的病因诊断，对 Alpha 进行针对性 AST 语法树结构重构
  2. 实现 5 大核心修复突变规则:
     - 衰减平滑突变 (针对 HIGH_TURNOVER): 注入 ts_decay_linear(x, 10) 或 ts_mean
     - 细分行业中性化突变 (针对 LOW_SUB_UNIVERSE_SHARPE): 注入 group_neutralize(x, subindustry)
     - 符号反转突变 (针对 NEGATIVE_SHARPE): 自动注入 reverse / 负号反转
     - 非线性幂次压缩突变 (针对 MARGINAL_SHARPE): 注入 signed_power(rank(x), 0.5)
     - 窗口放大突变: 将过敏的超短期时序算子窗口扩大 (5 -> 22 -> 66)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from alpha_operator_framework.domain.ast import (
    canonicalize_expression,
    parse_expression,
    to_canonical_string,
    validate_expression,
)
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.distill.diagnostic import FailureDiagnosis, FailureMode


class AlphaMutator:
    """AST 基因突变修复器."""

    @staticmethod
    def mutate_expression(expr_str: str, mode: FailureMode) -> List[str]:
        """根据指定的失败模式生成候选突变表达式字符串列表."""
        try:
            can_expr = to_canonical_string(expr_str)
        except Exception:
            can_expr = expr_str.strip()

        mutations: List[str] = []

        if mode == FailureMode.NEGATIVE_SHARPE:
            mutations.append(f"-1.0 * ({can_expr})")
            mutations.append(f"reverse({can_expr})")

        elif mode == FailureMode.HIGH_TURNOVER:
            # 1. 顶层线性衰减平滑
            mutations.append(f"ts_decay_linear({can_expr}, 10)")
            # 2. 顶层滚动均值平滑
            mutations.append(f"ts_mean({can_expr}, 5)")
            # 3. 截面秩化
            mutations.append(f"rank({can_expr})")

        elif mode == FailureMode.LOW_SUB_UNIVERSE_SHARPE:
            # 1. 细分行业中性化
            mutations.append(f"group_neutralize({can_expr}, subindustry)")
            # 2. 板块中性化
            mutations.append(f"group_neutralize({can_expr}, sector)")
            # 3. 分组秩化
            mutations.append(f"group_rank({can_expr}, industry)")

        elif mode == FailureMode.MARGINAL_SHARPE:
            # 1. 保号非线性离群值压缩
            mutations.append(f"signed_power(rank({can_expr}), 0.5)")
            # 2. 22 日时序分位数
            mutations.append(f"ts_rank({can_expr}, 22)")
            # 3. 截面标准化
            mutations.append(f"zscore({can_expr})")

        elif mode == FailureMode.PROD_CORRELATION:
            # 剥离行业共性
            mutations.append(f"group_neutralize({can_expr}, industry)")

        # 校验并规范化生成的突变表达式
        valid_can_mutations: List[str] = []
        seen = {can_expr}

        for mut in mutations:
            try:
                norm = to_canonical_string(mut)
                v_res = validate_expression(norm)
                if v_res.is_valid and norm not in seen:
                    valid_can_mutations.append(norm)
                    seen.add(norm)
            except Exception:
                continue

        return valid_can_mutations

    def mutate_task(
        self,
        task: Task,
        diagnosis: FailureDiagnosis,
        max_candidates: int = 3,
    ) -> List[Task]:
        """对指定的失败 Task 进行基因突变，返回生成的新 Task 候选列表."""
        mutated_exprs = self.mutate_expression(task.expression, diagnosis.primary_cause)
        new_tasks: List[Task] = []

        for idx, new_expr in enumerate(mutated_exprs[:max_candidates]):
            mutated_task = Task(
                expression=new_expr,
                template_index=task.template_index,
                family=f"{task.family}_mutated",
                fields_per_alpha=task.fields_per_alpha,
                expression_origin=f"mutation_{diagnosis.primary_cause.value}",
                decay=task.decay,
                base_fields=task.base_fields,
                meta={
                    **task.meta,
                    "mutated_from": diagnosis.alpha_id or task.expression,
                    "primary_failure": diagnosis.primary_cause.value,
                    "mutation_variant": idx,
                },
            )
            new_tasks.append(mutated_task)

        return new_tasks


def auto_repair_failed_alphas(
    alpha_rows: Sequence[Dict[str, Any]],
    max_mutations_per_alpha: int = 2,
) -> List[Task]:
    """批量对失败/边缘 Alpha 执行自动诊断并生成基因突变修复 Task 列表."""
    from alpha_operator_framework.distill.diagnostic import diagnose_alpha_failure

    mutator = AlphaMutator()
    repaired_tasks: List[Task] = []

    for row in alpha_rows:
        diagnosis = diagnose_alpha_failure(row)
        if diagnosis.is_repairable:
            dummy_task = Task(
                expression=diagnosis.expression,
                template_index=0,
                family="repaired",
                fields_per_alpha=1,
            )
            mutated = mutator.mutate_task(dummy_task, diagnosis, max_candidates=max_mutations_per_alpha)
            repaired_tasks.extend(mutated)

    return repaired_tasks
