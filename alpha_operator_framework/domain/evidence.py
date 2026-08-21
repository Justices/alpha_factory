"""研究证据等级与提交决策状态机 (Evidence Level & Decision State Machine).

严格定义 Alpha 研发全生命周期中的证据可信度边界，杜绝离线模拟/沙盒诊断伪造真实平台指标。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class EvidenceLevel(str, Enum):
    """Alpha 绩效数据的证据可信度等级."""

    SYNTHETIC = "synthetic"                      # 1. 纯合成/随机矩阵上的语法与运算测试
    SANDBOX_DIAGNOSTIC = "sandbox_diagnostic"    # 2. 本地快速截面 IC 与单调性信号诊断 (不计交易摩擦)
    PLATFORM_IS = "platform_is"                  # 3. WorldQuant BRAIN 官方服务器样本内 (IS) 真实回测
    PLATFORM_OS = "platform_os"                  # 4. 平台严格样本外 (OOS) 或前向 Walk-Forward 测试
    SUBMISSION_READY = "submission_ready"        # 5. 经过 locked OOS、18 项 Checks 全 PASS 且通过终审的正式候选

    @property
    def is_platform_verified(self) -> bool:
        """是否属于真实平台验证的级别."""
        return self in (
            EvidenceLevel.PLATFORM_IS,
            EvidenceLevel.PLATFORM_OS,
            EvidenceLevel.SUBMISSION_READY,
        )

    @property
    def is_eligible_for_submission(self) -> bool:
        """是否有资格进入真实提交候选池 (严格仅限 SUBMISSION_READY)."""
        return self == EvidenceLevel.SUBMISSION_READY


class DecisionState(str, Enum):
    """Alpha 提交治理状态机."""

    DRAFT = "draft"                              # 初始生成草稿
    SIMULATED = "simulated"                      # 回测完成 (包含沙盒诊断或平台回测)
    DIAGNOSED = "diagnosed"                      # 完成失败诊断与病因归类
    CHECKS_VERIFIED = "checks_verified"          # 完成平台 18 项 Checks 终审审计
    SUBMISSION_READY = "submission_ready"        # 终审达标，待提交
    SUBMITTED = "submitted"                      # 已正式向平台提交
    REJECTED = "rejected"                        # 淘汰废弃 / 剪枝

    def can_transition_to(self, target: DecisionState, evidence: EvidenceLevel) -> bool:
        """校验状态流转的合法性 (显式有向图拓扑 + 证据等级约束)."""
        valid_targets = STATE_TRANSITIONS.get(self, set())
        if target not in valid_targets:
            return False

        # 证据等级硬约束:
        if target == DecisionState.CHECKS_VERIFIED:
            if not evidence.is_platform_verified:
                return False
        elif target in (DecisionState.SUBMISSION_READY, DecisionState.SUBMITTED):
            if evidence != EvidenceLevel.SUBMISSION_READY:
                return False

        return True


# 显式状态转移有向图 (Adjacency List)
STATE_TRANSITIONS: Dict[DecisionState, Set[DecisionState]] = {
    DecisionState.DRAFT: {DecisionState.SIMULATED, DecisionState.REJECTED},
    DecisionState.SIMULATED: {DecisionState.DIAGNOSED, DecisionState.REJECTED},
    DecisionState.DIAGNOSED: {DecisionState.CHECKS_VERIFIED, DecisionState.REJECTED},
    DecisionState.CHECKS_VERIFIED: {DecisionState.SUBMISSION_READY, DecisionState.REJECTED},
    DecisionState.SUBMISSION_READY: {DecisionState.SUBMITTED, DecisionState.REJECTED},
    DecisionState.SUBMITTED: {DecisionState.REJECTED},
    DecisionState.REJECTED: set(),
}


@dataclass
class SubmissionApprovalReport:
    """提交前 6 维证据综合审批报告."""

    approved: bool
    alpha_id: str
    rejection_reasons: List[str] = field(default_factory=list)
    locked_oos_passed: bool = False
    checks_passed: bool = False
    correlation_passed: bool = False
    cost_capacity_passed: bool = False
    lineage_verified: bool = False
    verdict_ready: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


class SubmissionApprovalEngine:
    """提交审批裁决引擎 — 严守 6 维证据准入红线."""

    @classmethod
    def evaluate(
        cls,
        alpha_id: str,
        evidence_level: EvidenceLevel,
        is_metrics: Dict[str, Any],
        oos_metrics: Optional[Dict[str, Any]] = None,
        checks: Optional[List[Dict[str, Any]]] = None,
        sc_value: Optional[float] = None,
        pc_value: Optional[float] = None,
        has_lineage_dag: bool = True,
        judge_verdict: Optional[str] = None,
    ) -> SubmissionApprovalReport:
        """评估候选 Alpha 是否满足提升至 SUBMISSION_READY 的全部 6 类证据要求."""
        reasons: List[str] = []

        # 1. Locked OOS 证据验证
        oos_passed = False
        if oos_metrics and float(oos_metrics.get("sharpe", 0.0)) >= 1.25:
            oos_passed = True
        elif evidence_level in (EvidenceLevel.PLATFORM_OS, EvidenceLevel.SUBMISSION_READY):
            oos_passed = True
        else:
            reasons.append("缺少合格的 Locked-OOS 样本外实测证据 (OOS Sharpe < 1.25 或未测)")

        # 2. 18 项平台 Checks 验证
        checks_list = checks or []
        failed_checks = [c.get("name") for c in checks_list if c.get("result") != "PASS"]
        checks_passed = len(checks_list) > 0 and len(failed_checks) == 0
        if not checks_passed:
            reasons.append(f"平台 Checks 未全部 PASS (失败项: {failed_checks or '未执行Checks'})")

        # 3. SC / PC 相关性门槛验证
        sc = sc_value if sc_value is not None else 1.0
        pc = pc_value if pc_value is not None else 1.0
        corr_passed = (sc <= 0.70) and (pc <= 0.70)
        if not corr_passed:
            reasons.append(f"自相关/母本相关性过高 (SC={sc:.2f}, PC={pc:.2f} > 0.70)")

        # 4. 成本、容量与换手率验证
        turnover = float(is_metrics.get("turnover", 0.0))
        margin = float(is_metrics.get("margin", 0.0))
        cost_passed = (0.01 <= turnover <= 0.70) and (margin >= 4.0)
        if not cost_passed:
            reasons.append(f"换手率或 Margin 摩擦不达标 (Turnover={turnover:.1%}, Margin={margin:.1f}bp)")

        # 5. 谱系与工件 DAG 验证
        lineage_passed = bool(has_lineage_dag)
        if not lineage_passed:
            reasons.append("缺少完整谱系生成与变异溯源图谱")

        # 6. AlphaJudge / 人工评级验证
        verdict_passed = (judge_verdict == "READY")
        if not verdict_passed:
            reasons.append(f"AlphaJudge 未裁决为 READY (当前裁决: {judge_verdict or 'NONE'})")

        all_approved = (
            oos_passed
            and checks_passed
            and corr_passed
            and cost_passed
            and lineage_passed
            and verdict_passed
        )

        return SubmissionApprovalReport(
            approved=all_approved,
            alpha_id=alpha_id,
            rejection_reasons=reasons,
            locked_oos_passed=oos_passed,
            checks_passed=checks_passed,
            correlation_passed=corr_passed,
            cost_capacity_passed=cost_passed,
            lineage_verified=lineage_passed,
            verdict_ready=verdict_passed,
            details={
                "sc": sc,
                "pc": pc,
                "turnover": turnover,
                "margin": margin,
            },
        )


# Alias
DecisionApprovalEngine = SubmissionApprovalEngine

