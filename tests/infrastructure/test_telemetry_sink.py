"""External telemetry sink tests."""

import json

from alpha_operator_framework.infrastructure.telemetry import JsonLinesTelemetrySink, ResearchTelemetry


def test_jsonlines_sink_writes_telemetry_snapshot(tmp_path) -> None:
    telemetry = ResearchTelemetry()
    telemetry.record_backtests_completed(2)
    path = tmp_path / "metrics.jsonl"

    JsonLinesTelemetrySink(path).publish(telemetry)

    assert json.loads(path.read_text(encoding="utf-8")) ["backtests_completed"] == 2
