"""Unit tests for EvidenceLevel, Truth Boundaries, TrialLedger, and Anti-Overfitting improvements."""

import pytest
import numpy as np

from alpha_operator_framework.domain.evidence import (
    DecisionState,
    EvidenceLevel,
    SubmissionApprovalEngine,
)
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge, JudgeVerdict
from alpha_operator_framework.domain.overfitting import (
    TrialLedger,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    sharpe_haircut,
)
from alpha_operator_framework.domain.sandbox.engine import SignalDiagnosticEngine


def test_evidence_level_truth_boundaries():
    """测试证据等级属性与提交资格红线 (仅 SUBMISSION_READY 具备提交候选资格)."""
    assert not EvidenceLevel.SYNTHETIC.is_platform_verified
    assert not EvidenceLevel.SANDBOX_DIAGNOSTIC.is_platform_verified
    assert EvidenceLevel.PLATFORM_IS.is_platform_verified
    assert EvidenceLevel.PLATFORM_OS.is_platform_verified
    assert EvidenceLevel.SUBMISSION_READY.is_platform_verified

    # 提交资格红线: 仅 SUBMISSION_READY 具备
    assert not EvidenceLevel.SYNTHETIC.is_eligible_for_submission
    assert not EvidenceLevel.SANDBOX_DIAGNOSTIC.is_eligible_for_submission
    assert not EvidenceLevel.PLATFORM_IS.is_eligible_for_submission
    assert not EvidenceLevel.PLATFORM_OS.is_eligible_for_submission
    assert EvidenceLevel.SUBMISSION_READY.is_eligible_for_submission


def test_decision_state_directed_transitions():
    """测试决策状态机严格有向图流转与证据等级约束."""
    # 1. DRAFT 合法跳转为 SIMULATED 或 REJECTED
    draft = DecisionState.DRAFT
    assert draft.can_transition_to(DecisionState.SIMULATED, EvidenceLevel.SANDBOX_DIAGNOSTIC)
    assert draft.can_transition_to(DecisionState.REJECTED, EvidenceLevel.SYNTHETIC)
    # 不允许跨越跃迁 (如 DRAFT -> CHECKS_VERIFIED)
    assert not draft.can_transition_to(DecisionState.CHECKS_VERIFIED, EvidenceLevel.PLATFORM_IS)
    assert not draft.can_transition_to(DecisionState.SUBMISSION_READY, EvidenceLevel.PLATFORM_IS)

    # 2. DIAGNOSED -> CHECKS_VERIFIED 需要 platform_is
    diag = DecisionState.DIAGNOSED
    assert diag.can_transition_to(DecisionState.CHECKS_VERIFIED, EvidenceLevel.PLATFORM_IS)
    assert not diag.can_transition_to(DecisionState.CHECKS_VERIFIED, EvidenceLevel.SANDBOX_DIAGNOSTIC)

    # 3. CHECKS_VERIFIED -> SUBMISSION_READY 严格要求 SUBMISSION_READY 证据等级
    checks_v = DecisionState.CHECKS_VERIFIED
    assert not checks_v.can_transition_to(DecisionState.SUBMISSION_READY, EvidenceLevel.PLATFORM_IS)
    assert checks_v.can_transition_to(DecisionState.SUBMISSION_READY, EvidenceLevel.SUBMISSION_READY)


def test_submission_approval_engine_6_dimensions():
    """测试 6 维提交证据审批引擎 (Locked-OOS, 18 Checks, SC/PC, 摩擦, 谱系, 裁决)."""
    # 1. 缺少 Locked-OOS 证据被拒绝
    rep1 = SubmissionApprovalEngine.evaluate(
        alpha_id="ALPHA_01",
        evidence_level=EvidenceLevel.PLATFORM_IS,
        is_metrics={"turnover": 0.15, "margin": 6.0},
        oos_metrics=None,
        checks=[{"name": "LOW_SHARPE", "result": "PASS"}],
        sc_value=0.20,
        pc_value=0.20,
        judge_verdict="READY",
    )
    assert not rep1.approved
    assert any("Locked-OOS" in r for r in rep1.rejection_reasons)

    # 2. 6 维全部达标获批
    rep2 = SubmissionApprovalEngine.evaluate(
        alpha_id="ALPHA_02",
        evidence_level=EvidenceLevel.PLATFORM_OS,
        is_metrics={"turnover": 0.15, "margin": 6.0},
        oos_metrics={"sharpe": 1.45},
        checks=[{"name": "LOW_SHARPE", "result": "PASS"}],
        sc_value=0.30,
        pc_value=0.25,
        judge_verdict="READY",
    )
    assert rep2.approved
    assert len(rep2.rejection_reasons) == 0


def test_alpha_judge_rejects_unverified_candidates():
    """测试 AlphaJudge 绝不对未经平台实测的候选给予 READY 评级."""
    judge = AlphaJudge()

    # 模拟沙盒回测候选 (高夏普但在沙盒运行)
    sandbox_cand = {
        "alpha_id": "SANDBOX_01",
        "expression": "group_neutralize(rank(returns), subindustry)",
        "sharpe": 1.80,
        "fitness": 1.50,
        "turnover": 0.20,
        "pc_value": 0.10,
        "sc_value": 0.10,
        "evidence_level": EvidenceLevel.SANDBOX_DIAGNOSTIC.value,
        "checks": [],
    }

    report = judge.judge_candidate(sandbox_cand)
    assert report.verdict != JudgeVerdict.READY
    assert not report.platform_checks_passed
    assert "NOT_PLATFORM_VERIFIED" in report.failed_checks


def test_trial_ledger_dynamic_effective_trials():
    """测试试验账本真实累计与有效试验自由度对 DSR 的统计衰减."""
    ledger = TrialLedger()

    for i in range(10):
        ledger.record_trial(f"expr_{i}", family="momentum")
    for i in range(40):
        ledger.record_trial(f"reversion_{i}", family="reversion")

    assert ledger.get_effective_trials("momentum") == 7  # 1 + 9 * 0.65 = 6.85 -> 7
    assert ledger.get_effective_trials("reversion") == 26  # 1 + 39 * 0.65 = 26.35 -> 26
    assert ledger.get_effective_trials() == 33  # 1 + 49 * 0.65 = 32.85 -> 33

    # 验证 DSR 随试验次数增加发生严格统计折损
    sharpe = 1.50
    dsr_10 = deflated_sharpe_ratio(sharpe, trial_count=10, t_days=504)
    dsr_50 = deflated_sharpe_ratio(sharpe, trial_count=50, t_days=504)
    dsr_500 = deflated_sharpe_ratio(sharpe, trial_count=500, t_days=504)

    assert dsr_10 > dsr_50 > dsr_500


def test_field_spec_quality_priority_profile():
    """测试字段画像的质量与新颖性评分."""
    clean_alt_field = FieldSpec(
        id="insider_buy",
        dataset_id="insider",
        type="MATRIX",
        coverage=0.90,
        user_count=5,
        alpha_count=10,
        novelty_priority=1.5,
    )

    crowded_pv_field = FieldSpec(
        id="vwap",
        dataset_id="pv1",
        type="MATRIX",
        coverage=0.98,
        user_count=500,
        alpha_count=5000,
        novelty_priority=0.5,
    )

    assert clean_alt_field.quality_priority_score > crowded_pv_field.quality_priority_score
