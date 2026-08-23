"""Operational telemetry tests."""

from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.models import ExperimentBatch
from alpha_operator_framework.infrastructure.telemetry import ResearchTelemetry
import json


def test_telemetry_counts_batch_transitions() -> None:
    batch = ExperimentBatch("batch", "key")
    telemetry = ResearchTelemetry()
    event = transition(batch, BatchState.SUBMITTED)

    telemetry.record_transition(batch, event)

    assert telemetry.snapshot()["batch_transitions"]["SUBMITTED"] == 1


def test_telemetry_records_pruning_quota_and_retryable_failures() -> None:
    telemetry = ResearchTelemetry()
    batch = ExperimentBatch("batch", "key")

    telemetry.record_pruning_reason("AST_INVALID")
    telemetry.record_quota(planned=3, consumed=2)
    telemetry.record_transition(batch, transition(batch, BatchState.SUBMITTED))
    telemetry.record_transition(batch, transition(batch, BatchState.RUNNING))
    telemetry.record_transition(batch, transition(batch, BatchState.PARTIAL_FAILED))

    snapshot = telemetry.snapshot()
    assert snapshot["pruning_reasons"]["AST_INVALID"] == 1
    assert snapshot["quota"] == {"planned": 3, "consumed": 2}
    assert snapshot["retryable_batches"] == 1


def test_telemetry_exports_json_snapshot() -> None:
    telemetry = ResearchTelemetry()
    telemetry.record_backtests_completed(2)

    assert json.loads(telemetry.export_json())["backtests_completed"] == 2
