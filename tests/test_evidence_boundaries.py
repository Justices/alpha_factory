"""Unit tests for EvidenceLevel, Truth Boundaries, TrialLedger, and Anti-Overfitting improvements."""

import pytest
import numpy as np

from alpha_operator_framework.domain.evidence import EvidenceLevel, DecisionState
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge, JudgeVerdict
from alpha_operator_framework.domain.overfitting import (
    TrialLedger,
    compute_dsr,
    compute_haircut_sharpe,
    compute_psr,
)
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.domain.sandbox.engine import SignalDiagnosticEngine


def test_evidence_level_truth_boundaries():
    """测试证据等级属性与提交资格红线."""
    assert not EvidenceLevel.SYNTHETIC.is_platform_verified
    assert not EvidenceLevel.SANDBOX_DIAGNOSTIC.is_platform_verified
    assert EvidenceLevel.PLATFORM_IS.is_platform_verified
    assert EvidenceLevel.PLATFORM_OS.is_platform_verified
    assert EvidenceLevel.SUBMISSION_READY.is_platform_verified

    # 决策状态机流转约束
    state = DecisionState.DRAFT
    assert state.can_transition_to(DecisionState.SIMULATED, EvidenceLevel.SANDBOX_DIAGNOSTIC)
    # 沙盒证据绝对不允许流转到 CHECKS_VERIFIED 或 SUBMISSION_READY
    assert not state.can_transition_to(DecisionState.CHECKS_VERIFIED, EvidenceLevel.SANDBOX_DIAGNOSTIC)
    assert not state.can_transition_to(DecisionState.SUBMISSION_READY, EvidenceLevel.SANDBOX_DIAGNOSTIC)
    # 平台证据允许流转
    assert state.can_transition_to(DecisionState.CHECKS_VERIFIED, EvidenceLevel.PLATFORM_IS)
    assert state.can_transition_to(DecisionState.SUBMISSION_READY, EvidenceLevel.PLATFORM_IS)


def test_alpha_judge_rejects_unverified_candidates():
    """测试 AlphaJudge 绝不对未经平台实测的候选给予 READY 评级."""
    judge = AlphaJudge()

    # 1. 模拟沙盒回测候选 (高夏普但在沙盒运行)
    sandbox_cand = {
        "alpha_id": "SANDBOX_01",
        "expression": "group_neutralize(rank(close), subindustry)",
        "sharpe": 1.80,
        "fitness": 1.50,
        "turnover": 0.20,
        "pc_value": 0.10,
        "sc_value": 0.10,
        "evidence_level": EvidenceLevel.SANDBOX_DIAGNOSTIC.value,
        "checks": [],
    }

    report = judge.judge_candidate(sandbox_cand)
    # 必须为 REVIEW (沙盒预筛) 或 BLOCK，绝不允许 READY
    assert report.verdict != JudgeVerdict.READY
    assert not report.platform_checks_passed
    assert "NOT_PLATFORM_VERIFIED" in report.failed_checks


def test_trial_ledger_dynamic_effective_trials():
    """测试试验账本真实累计与有效试验自由度对 DSR 的统计衰减."""
    ledger = TrialLedger()

    # 记录 10 次试验
    for i in range(10):
        ledger.record_trial(f"expr_{i}", family="momentum")

    # 记录另外 40 次均值回归试验
    for i in range(40):
        ledger.record_trial(f"reversion_{i}", family="reversion")

    assert ledger.get_effective_trials("momentum") == 10
    assert ledger.get_effective_trials("reversion") == 40
    assert ledger.get_effective_trials() == 50

    # 验证 DSR 随试验次数增加发生严格统计折损
    sharpe = 1.50
    dsr_10 = compute_dsr(sharpe, trial_count=10, t_days=504)
    dsr_50 = compute_dsr(sharpe, trial_count=50, t_days=504)
    dsr_500 = compute_dsr(sharpe, trial_count=500, t_days=504)

    assert dsr_10 > dsr_50 > dsr_500


def test_field_spec_quality_priority_profile():
    """测试字段画像画像的质量与新颖性评分."""
    # 优质另类新颖字段 (高覆盖, 低拥挤, 高新颖)
    clean_alt_field = FieldSpec(
        id="insider_buy",
        dataset_id="insider",
        type="MATRIX",
        coverage=0.90,
        user_count=5,
        alpha_count=10,
        novelty_priority=1.5,
    )

    # 拥挤传统量价字段 (高覆盖, 极度拥挤, 低新颖)
    crowded_pv_field = FieldSpec(
        id="close",
        dataset_id="pv1",
        type="MATRIX",
        coverage=0.98,
        user_count=500,
        alpha_count=5000,
        novelty_priority=0.5,
    )

    assert clean_alt_field.quality_priority_score > crowded_pv_field.quality_priority_score
