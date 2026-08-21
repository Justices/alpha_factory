"""Alpha 终审评级与提交优先级决策引擎 (Alpha Judge & Priority Evaluator).

功能:
  1. 综合平台硬性指标、实战红线审查 (Extra Rubrics) 与价值因子多样性增量 (Delta Diversity)
  2. 产出权威终审评级: READY (立即优先提交) / REVIEW (需复核微调) / BLOCK (禁止提交)
  3. 计算综合优先级得分 (Priority Score)，指导用户优先提交边际收益最大的 Alpha
  4. 自动生成具体、可落地的改进建议清单 (Actionable Recommendations)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from alpha_operator_framework.domain.judge.diversity import (
    ValueFactorDiversity,
    compute_value_factor_diversity,
    project_diversity_after_submission,
)
from alpha_operator_framework.domain.judge.rubrics import (
    RubricResult,
    RubricSeverity,
    RubricStatus,
    evaluate_all_rubrics,
)


class JudgeVerdict(str, Enum):
    """终审评级结论."""

    READY = "READY"    # 全绿达标，高价值因子增量，建议立即提交
    REVIEW = "REVIEW"  # 基本合格但存在轻度违规或缺失机理说明，需复核
    BLOCK = "BLOCK"    # 存在硬性指标违规或高相关冲突，禁止提交


@dataclass
class JudgeReport:
    """单个 Alpha 的完整终审评估报告."""

    alpha_id: str
    expression: str
    verdict: JudgeVerdict
    priority_score: float                        # 综合提交优先级打分 (越高越优先)
    platform_checks_passed: bool                # 平台 18 项硬性指标是否全过
    failed_checks: List[str]                    # 平台未通过项名称
    rubric_results: List[RubricResult]          # 实战红线审查明细
    current_diversity_score: float              # 当前存量多样性总分
    projected_diversity_delta: float            # 提交本因子带来的多样性增量 Δdiversity
    actionable_recommendations: List[str]       # 具象化改进建议
    metrics: Dict[str, Any] = field(default_factory=dict)


class AlphaJudge:
    """Alpha 终审裁判员与优先级排序器."""

    def __init__(self, submitted_alphas: Optional[Sequence[Dict[str, Any]]] = None):
        self.submitted_alphas = list(submitted_alphas or [])
        self.current_diversity = compute_value_factor_diversity(self.submitted_alphas)

    def judge_candidate(
        self,
        candidate_detail: Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None,
    ) -> JudgeReport:
        """对单个 Alpha 执行两道门质量审查、多样性增量推演与评级打分."""
        alpha_id = str(candidate_detail.get("alpha_id") or candidate_detail.get("id") or "")
        expr = str(candidate_detail.get("expression") or candidate_detail.get("regular") or "")

        # 1. 提取平台关键指标
        sharpe = float(candidate_detail.get("sharpe") or (candidate_detail.get("is", {}) or {}).get("sharpe") or 0.0)
        fitness = float(candidate_detail.get("fitness") or (candidate_detail.get("is", {}) or {}).get("fitness") or 0.0)
        turnover = float(candidate_detail.get("turnover") or (candidate_detail.get("is", {}) or {}).get("turnover") or 0.0)
        pc = float(candidate_detail.get("pc_value") or candidate_detail.get("prodCorrelation") or 0.0)
        sc = float(candidate_detail.get("sc_value") or candidate_detail.get("selfCorrelation") or 0.0)

        # 2. 检查平台硬性 checks 列表
        checks = candidate_detail.get("checks") or []
        failed_checks: List[str] = []
        for c in checks:
            if isinstance(c, dict) and c.get("result") == "FAIL":
                failed_checks.append(str(c.get("name") or "UNKNOWN_CHECK"))

        # 0. 证据等级检查 (红线: 必须平台实测才允许 READY)
        evidence_level_str = str(candidate_detail.get("evidence_level") or "platform_is")
        is_platform_verified = evidence_level_str in ("platform_is", "platform_os", "submission_ready")

        # 硬性门槛判断 (Sharpe >= 1.25, Fitness >= 1.0, Turnover <= 0.70, PC/SC <= 0.70)
        platform_passed = (
            is_platform_verified
            and len(failed_checks) == 0
            and sharpe >= 1.25
            and fitness >= 1.0
            and turnover <= 0.70
            and pc < 0.70
            and sc < 0.70
        )
        if not is_platform_verified:
            failed_checks.append("NOT_PLATFORM_VERIFIED")
        if sharpe < 1.25 and "LOW_SHARPE" not in failed_checks:
            failed_checks.append("LOW_SHARPE")
        if fitness < 1.0 and "LOW_FITNESS" not in failed_checks:
            failed_checks.append("LOW_FITNESS")
        if turnover > 0.70 and "HIGH_TURNOVER" not in failed_checks:
            failed_checks.append("HIGH_TURNOVER")
        if pc >= 0.70 and "HIGH_PROD_CORRELATION" not in failed_checks:
            failed_checks.append("HIGH_PROD_CORRELATION")

        # 3. 执行实战红线审查 (Extra Rubrics)
        rubric_results = evaluate_all_rubrics(expr, candidate_detail, meta=meta)

        # 4. 价值因子多样性增量推演 (Delta Diversity)
        _, delta_diversity = project_diversity_after_submission(self.current_diversity, candidate_detail)

        # 5. 综合评定 Verdict
        has_block_rubric_fail = any(
            r.severity == RubricSeverity.BLOCK and r.status == RubricStatus.FAIL for r in rubric_results
        )
        has_review_rubric_warn = any(r.status in (RubricStatus.WARN, RubricStatus.FAIL) for r in rubric_results)

        recs: List[str] = []

        if not is_platform_verified:
            verdict = JudgeVerdict.REVIEW if sharpe > 0 else JudgeVerdict.BLOCK
            recs.append("【证据级别: 沙盒信号初筛】尚未在 WorldQuant BRAIN 真实平台在线回测，严禁直接提交！")
        elif not platform_passed or has_block_rubric_fail:
            verdict = JudgeVerdict.BLOCK
            if failed_checks:
                recs.append(f"平台硬性未过项: {', '.join(failed_checks)}，禁止直接提交")
        elif has_review_rubric_warn:
            verdict = JudgeVerdict.REVIEW
            for r in rubric_results:
                if r.status in (RubricStatus.WARN, RubricStatus.FAIL) and r.action_hint:
                    recs.append(f"[{r.title}] {r.reason} -> 建议: {r.action_hint}")
        else:
            verdict = JudgeVerdict.READY
            recs.append("各项指标与实战红线全部合规，具备高价值因子增量，建议优先提交！")

        if len(recs) < 3 and verdict != JudgeVerdict.READY:
            recs.append("建议在提交前使用真实平台批量模拟验证子宇宙夏普与日度换手率稳定性")

        # 6. 计算综合提交优先级得分 Priority Score
        verdict_base = 100.0 if verdict == JudgeVerdict.READY else (40.0 if verdict == JudgeVerdict.REVIEW else 0.0)
        diversity_bonus = max(-10.0, min(20.0, delta_diversity * 500.0))
        sharpe_bonus = min(30.0, sharpe * 10.0)
        fitness_bonus = min(20.0, fitness * 10.0)

        priority_score = round(verdict_base + diversity_bonus + sharpe_bonus + fitness_bonus, 2)

        return JudgeReport(
            alpha_id=alpha_id,
            expression=expr,
            verdict=verdict,
            priority_score=priority_score,
            platform_checks_passed=platform_passed,
            failed_checks=failed_checks,
            rubric_results=rubric_results,
            current_diversity_score=self.current_diversity.diversity_score,
            projected_diversity_delta=delta_diversity,
            actionable_recommendations=recs,
            metrics={
                "sharpe": sharpe,
                "fitness": fitness,
                "turnover": turnover,
                "pc_value": pc,
                "sc_value": sc,
            },
        )

    def rank_candidates(
        self,
        candidates: Sequence[Dict[str, Any]],
        meta_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[JudgeReport]:
        """批量对候选 Alpha 执行终审评估并按提交优先级降序排列."""
        reports: List[JudgeReport] = []
        meta_dict = meta_dict or {}

        for c in candidates:
            cid = str(c.get("alpha_id") or c.get("id") or "")
            meta = meta_dict.get(cid)
            rep = self.judge_candidate(c, meta=meta)
            reports.append(rep)

        # 优先级降序排列 (Priority Score 从高到低)
        reports.sort(key=lambda r: r.priority_score, reverse=True)
        return reports
