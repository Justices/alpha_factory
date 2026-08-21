"""研究证据等级与提交决策状态机 (Evidence Level & Decision State Machine).

严格定义 Alpha 研发全生命周期中的证据可信度边界，杜绝离线模拟/沙盒诊断伪造真实平台指标。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Set


class EvidenceLevel(str, Enum):
    """Alpha 绩效数据的证据可信度等级."""

    SYNTHETIC = "synthetic"                      # 1. 纯合成/随机矩阵上的语法与运算测试
    SANDBOX_DIAGNOSTIC = "sandbox_diagnostic"    # 2. 本地快速截面 IC 与单调性信号诊断 (不计交易摩擦)
    PLATFORM_IS = "platform_is"                  # 3. WorldQuant BRAIN 官方服务器样本内 (IS) 真实回测
    PLATFORM_OS = "platform_os"                  # 4. 平台严格样本外 (OOS) 或前向 Walk-Forward 测试
    SUBMISSION_READY = "submission_ready"        # 5. 平台 18 项 Checks 全部 PASS 且通过相关性终审的正式候选

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
        """是否有资格进入真实提交候选池 (红线约束)."""
        return self in (
            EvidenceLevel.PLATFORM_IS,
            EvidenceLevel.PLATFORM_OS,
            EvidenceLevel.SUBMISSION_READY,
        )


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
        """校验状态流转的合法性 (含证据等级硬约束)."""
        # 红线: 非平台实测严禁流转为 CHECKS_VERIFIED 或 SUBMISSION_READY
        if target in (DecisionState.CHECKS_VERIFIED, DecisionState.SUBMISSION_READY, DecisionState.SUBMITTED):
            if not evidence.is_platform_verified:
                return False
        return True
