"""Fail-closed submission outbox tests."""

from __future__ import annotations

import pytest

from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.infrastructure.submission import CnhkMcpSubmissionGateway, SubmissionNotAvailable, SqliteSubmissionOutbox
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
