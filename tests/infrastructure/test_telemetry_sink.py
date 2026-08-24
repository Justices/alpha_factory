"""External telemetry sink tests."""

import json

from alpha_operator_framework.infrastructure.telemetry import JsonLinesTelemetrySink, PrometheusTelemetryAdapter, ResearchTelemetry


def test_jsonlines_sink_writes_telemetry_snapshot(tmp_path) -> None:
    telemetry = ResearchTelemetry()
    telemetry.record_backtests_completed(2)
    path = tmp_path / "metrics.jsonl"

    JsonLinesTelemetrySink(path).publish(telemetry)

    assert json.loads(path.read_text(encoding="utf-8")) ["backtests_completed"] == 2


def test_prometheus_adapter_renders_the_same_telemetry_snapshot() -> None:
    telemetry = ResearchTelemetry()
    telemetry.record_backtests_completed(2)
    telemetry.record_pruning_reason("AST_INVALID")

    rendered = PrometheusTelemetryAdapter(telemetry).render()

    assert "alpha_factory_backtests_completed 2" in rendered
    assert 'alpha_factory_pruning_reasons{reason="AST_INVALID"} 1' in rendered
