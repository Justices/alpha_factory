"""Fail-closed submission outbox tests."""

from __future__ import annotations

import pytest

from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.infrastructure.submission import (
    ConfiguredSubmissionEvidenceGateway,
    CnhkMcpSubmissionGateway,
    SubmissionNotAvailable,
    SubmissionOutboxWorker,
    SqliteSubmissionOutbox,
)
from alpha_operator_framework.knowledge.submission import SubmissionCase, SubmissionEvidence


def test_outbox_persists_only_approved_submission_case(tmp_path) -> None:
    result = BacktestResult("task", "rank(returns)", 1.6, 1.1, 0.2, 5.0, True, "alpha-1")
    case = SubmissionCase.from_result(result, SubmissionEvidence(True, True, True, True))
    outbox = SqliteSubmissionOutbox(tmp_path / "outbox.db")

    receipt = outbox.enqueue(case)

    assert receipt.platform_alpha_id == "alpha-1"
    with pytest.raises(SubmissionNotAvailable):
        outbox.dispatch(receipt)


def test_cnhkmcp_gateway_dispatches_approved_alpha_id() -> None:
    submitted = []
    gateway = CnhkMcpSubmissionGateway(submit=lambda alpha_id: submitted.append(alpha_id) or {"status": "ok"})

    result = gateway.dispatch(type("Receipt", (), {"platform_alpha_id": "alpha-1"})())

    assert submitted == ["alpha-1"]
    assert result == {"status": "ok"}


def test_submission_worker_dispatches_pending_receipt_once(tmp_path) -> None:
    case = SubmissionCase.from_result(
        BacktestResult("task", "rank(returns)", 1.6, 1.1, 0.2, 5.0, True, "alpha-1"),
        SubmissionEvidence(True, True, True, True),
    )
    outbox = SqliteSubmissionOutbox(tmp_path / "outbox.db")
    outbox.enqueue(case)
    submitted = []

    dispatched = SubmissionOutboxWorker(
        outbox,
        CnhkMcpSubmissionGateway(submit=lambda alpha_id: submitted.append(alpha_id)),
    ).process_pending()

    assert [receipt.platform_alpha_id for receipt in dispatched] == ["alpha-1"]
    assert submitted == ["alpha-1"]
    assert outbox.pending() == []


def test_configured_evidence_requires_explicit_authorization() -> None:
    result = BacktestResult("task", "rank(returns)", 1.6, 1.1, 0.2, 5.0, True, "alpha-1")
    records = {"alpha-1": {"correlation_checked": True, "capacity_checked": True, "lineage_verified": True}}

    unauthorized = ConfiguredSubmissionEvidenceGateway(records, authorized=False).evidence_for(result)
    authorized = ConfiguredSubmissionEvidenceGateway(records, authorized=True).evidence_for(result)

    assert unauthorized.authorized is False
    assert SubmissionCase.from_result(result, unauthorized).approve().is_approved is False
    assert SubmissionCase.from_result(result, authorized).approve().is_approved is True


def test_submission_worker_retries_transient_failures_with_a_bounded_budget(tmp_path) -> None:
    case = SubmissionCase.from_result(
        BacktestResult("task", "rank(returns)", 1.6, 1.1, 0.2, 5.0, True, "alpha-1"),
        SubmissionEvidence(True, True, True, True),
    )
    outbox = SqliteSubmissionOutbox(tmp_path / "outbox.db")
    outbox.enqueue(case)
    worker = SubmissionOutboxWorker(
        outbox,
        CnhkMcpSubmissionGateway(submit=lambda _: (_ for _ in ()).throw(RuntimeError("temporary"))),
        max_attempts=2,
    )

    worker.process_pending()
    assert [receipt.platform_alpha_id for receipt in outbox.pending()] == ["alpha-1"]
    worker.process_pending()

    assert outbox.pending() == []
    assert outbox.status_of("alpha-1") == ("FAILED", 2, "temporary")


def test_outbox_claim_prevents_two_workers_from_dispatching_the_same_case(tmp_path) -> None:
    outbox = SqliteSubmissionOutbox(tmp_path / "outbox.db")
    outbox.enqueue(SubmissionCase.from_result(
        BacktestResult("task", "rank(returns)", 1.6, 1.1, 0.2, 5.0, True, "alpha-1"),
        SubmissionEvidence(True, True, True, True),
    ))

    assert [receipt.platform_alpha_id for receipt in outbox.claim_pending()] == ["alpha-1"]
    assert outbox.claim_pending() == []
