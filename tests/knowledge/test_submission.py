"""Fail-closed submission approval tests."""

from __future__ import annotations

from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.knowledge.submission import SubmissionCase, SubmissionEvidence


def test_submission_fails_closed_without_verified_platform_evidence() -> None:
    result = BacktestResult("task", "rank(close)", 1.6, 1.1, 0.2, 5.0, True)

    approval = SubmissionCase.from_result(result).approve()

    assert approval.is_approved is False
    assert approval.reason == "MISSING_VERIFIED_PLATFORM_ALPHA"


def test_submission_requires_complete_evidence_and_explicit_authorization() -> None:
    result = BacktestResult("task", "rank(returns)", 1.6, 1.1, 0.2, 5.0, True, "alpha-1")
    incomplete = SubmissionCase.from_result(result).approve()
    complete = SubmissionCase.from_result(
        result,
        SubmissionEvidence(correlation_checked=True, capacity_checked=True, lineage_verified=True, authorized=True, record_verified=True),
    ).approve()

    assert incomplete.reason == "MISSING_CORRELATION_EVIDENCE"
    assert complete.is_approved is True
