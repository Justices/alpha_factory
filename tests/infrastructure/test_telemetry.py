"""Operational telemetry tests."""

from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.models import ExperimentBatch
from alpha_operator_framework.infrastructure.telemetry import ResearchTelemetry


def test_telemetry_counts_batch_transitions() -> None:
    batch = ExperimentBatch("batch", "key")
    telemetry = ResearchTelemetry()
    event = transition(batch, BatchState.SUBMITTED)

    telemetry.record_transition(batch, event)

    assert telemetry.snapshot()["batch_transitions"]["SUBMITTED"] == 1
