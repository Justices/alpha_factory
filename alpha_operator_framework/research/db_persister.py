"""文献研发成果与 Alpha 表达式持久化模块 (Research Database Persister).

功能:
  1. 将研报提取编译出的所有规范 AST 表达式自动入库 (alpha_expressions 表)
  2. 记录来源文献、第一算子、使用字段元数据及回测设定
  3. 将平台真实回测详情与 18 项 Checks 写入 alpha_details 及 alpha_checks 表
  4. 将 AlphaJudge 终审裁决与得分更新至工作流阶段 (wf_stage)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from alpha_operator_framework.database.models import AlphaDetail, AlphaExpression
from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.ast import (
    extract_ast_fields,
    parse_expression,
    to_canonical_string,
)
from alpha_operator_framework.domain.operators import extract_first_operator
from alpha_operator_framework.domain.families import Task

logger = logging.getLogger(__name__)


def compute_expression_sha(expression: str) -> str:
    """计算表达式规范 SHA256 哈希值."""
    canonical = to_canonical_string(expression)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def persist_research_pipeline_results(
    db: AlphaDatabase,
    paper_title: str,
    tasks: List[Task],
    settings: Dict[str, Any],
    platform_results: Optional[List[Any]] = None,
    ranked_candidates: Optional[List[Dict[str, Any]]] = None,
    source_type: Optional[str] = None,
) -> Dict[str, int]:
    """将研发展开的所有表达式、真实回测结果与终审排名完整落库.

    写入内容:
      1. alpha_expressions: 规范化表达式主数据 (去重插入, 记录精确 origin)
      2. alpha_details: 真实平台回测表现指标 (Sharpe, Fitness, Turnover, wf_stage等)
      3. alpha_checks: 平台全部 18 项 Checks 状态
    """
    conn = db._get_connection()
    now_iso = datetime.now().isoformat()

    inserted_exprs = 0
    saved_details = 0

    # 构建准确的 origin 标识 (文献 / 地毯式挖掘 / 进化闭环 / 超级因子)
    if source_type:
        origin_str = f"{source_type}:{paper_title}"
    elif any(k in paper_title.lower() for k in ("carpet", "mining", "discover", "prepare", "alternative")):
        origin_str = f"carpet_mining:{paper_title}"
    elif any(k in paper_title.lower() for k in ("super", "hrp", "orthogonal")):
        origin_str = f"super_alpha:{paper_title}"
    elif any(k in paper_title.lower() for k in ("loop", "evolution", "mutation")):
        origin_str = f"evolution:{paper_title}"
    else:
        origin_str = f"paper:{paper_title}"

    # 1. 表达式落库 (alpha_expressions)
    for task in tasks:
        raw_expr = task.expression if isinstance(task, Task) else task.get("expression", "")
        if not raw_expr:
            continue

        try:
            tree = parse_expression(raw_expr)
            can_expr = to_canonical_string(tree)
            expr_sha = hashlib.sha256(can_expr.encode("utf-8")).hexdigest()
            fields_used = list(extract_ast_fields(tree))
            first_op = extract_first_operator(can_expr)
        except Exception:
            can_expr = raw_expr
            expr_sha = hashlib.sha256(raw_expr.encode("utf-8")).hexdigest()
            fields_used = []
            first_op = ""

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO alpha_expressions (
                    expression_sha, expression, expression_origin, settings,
                    fields, status, first_operator, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(expression_sha) DO UPDATE SET
                    expression_origin = CASE WHEN alpha_expressions.expression_origin = '' THEN excluded.expression_origin ELSE alpha_expressions.expression_origin END,
                    status = CASE WHEN excluded.status = 'completed' THEN 'completed' ELSE alpha_expressions.status END,
                    fields = CASE WHEN excluded.fields != '[]' THEN excluded.fields ELSE alpha_expressions.fields END,
                    first_operator = CASE WHEN alpha_expressions.first_operator = '' THEN excluded.first_operator ELSE alpha_expressions.first_operator END,
                    updated_at = excluded.updated_at
                """,
                (
                    expr_sha,
                    can_expr,
                    origin_str,
                    json.dumps(settings, ensure_ascii=False),
                    json.dumps(fields_used, ensure_ascii=False),
                    "completed" if platform_results else "pending",
                    first_op,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
            inserted_exprs += 1
        except Exception as e:
            logger.warning(f"表达式落库异常 ({can_expr[:40]}): {e}")

    # 2. 真实平台回测结果落库 (alpha_details + alpha_checks)
    if platform_results:
        for p_res in platform_results:
            alpha_id = getattr(p_res, "alpha_id", "")
            raw_details = getattr(p_res, "raw_details", {})
            if not alpha_id or alpha_id.startswith("FAILED_"):
                continue

            try:
                # 调用 AlphaDatabase 内核方法，单事务写入 details + 全部 checks
                db.save_result_with_checks(alpha_id, raw_details, settings)
                saved_details += 1

                # 根据 AlphaJudge 裁决更新 wf_stage
                if ranked_candidates:
                    matched = next((c for c in ranked_candidates if c.get("alpha_id") == alpha_id), None)
                    if matched:
                        verdict = matched.get("verdict", "")
                        new_stage = "validated" if verdict == "READY" else ("needs_optimization" if verdict in ("REVIEW", "CONDITIONAL") else "failed")
                        db.update_wf_stage(alpha_id, new_stage)

            except Exception as e:
                logger.error(f"Alpha {alpha_id} 平台回测结果落库失败: {e}")

    elif ranked_candidates:
        # 沙盒回测模式下记录本地评估结果
        for c in ranked_candidates:
            aid = c.get("alpha_id", "")
            expr = c.get("expression", "")
            if not aid:
                continue

            sim_row = {
                "id": aid,
                "regular": {"code": expr},
                "is": {
                    "sharpe": c.get("sharpe", 0.0),
                    "fitness": c.get("fitness", 0.0),
                    "turnover": c.get("turnover", 0.0),
                    "margin": c.get("margin", 0.0),
                    "returns": c.get("returns", 0.0),
                    "drawdown": c.get("drawdown", 0.0),
                    "checks": [],
                },
                "settings": settings,
            }
            try:
                db.save_result_with_checks(aid, sim_row, settings)
                db.update_wf_stage(aid, "sandbox_screened")
                saved_details += 1
            except Exception as e:
                logger.warning(f"沙盒 Alpha {aid} 落库异常: {e}")

    return {
        "inserted_expressions": inserted_exprs,
        "saved_details": saved_details,
    }
