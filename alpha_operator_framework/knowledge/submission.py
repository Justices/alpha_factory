"""Fail-closed submission approval."""

from __future__ import annotations

from dataclasses import dataclass

from alpha_operator_framework.experiment.models import BacktestResult


@dataclass(frozen=True)
class ApprovalDecision:
    is_approved: bool
    reason: str


@dataclass(frozen=True)
class SubmissionEvidence:
    correlation_checked: bool = False
    capacity_checked: bool = False
    lineage_verified: bool = False
    authorized: bool = False


@dataclass(frozen=True)
class SubmissionCase:
    result: BacktestResult
    evidence: SubmissionEvidence = SubmissionEvidence()

    @classmethod
    def from_result(
        cls,
        result: BacktestResult,
        evidence: SubmissionEvidence | None = None,
    ) -> "SubmissionCase":
        return cls(result, evidence or SubmissionEvidence())

    def approve(self) -> ApprovalDecision:
        if not self.result.platform_alpha_id:
            return ApprovalDecision(False, "MISSING_VERIFIED_PLATFORM_ALPHA")
        if not self.result.checks_passed:
            return ApprovalDecision(False, "FAILED_PLATFORM_CHECKS")
        if not self.evidence.correlation_checked:
            return ApprovalDecision(False, "MISSING_CORRELATION_EVIDENCE")
        if not self.evidence.capacity_checked:
            return ApprovalDecision(False, "MISSING_CAPACITY_EVIDENCE")
        if not self.evidence.lineage_verified:
            return ApprovalDecision(False, "MISSING_LINEAGE_EVIDENCE")
        if not self.evidence.authorized:
            return ApprovalDecision(False, "SUBMISSION_NOT_AUTHORIZED")
        return ApprovalDecision(True, "APPROVED")
