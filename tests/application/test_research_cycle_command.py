"""CLI composition tests for the new research-cycle entry point."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import alpha_machine
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import EventType
from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime


def test_research_rebuild_command_uses_runtime_projections_only(monkeypatch, tmp_path) -> None:
    called = []
    runtime = SimpleNamespace(event_store=object(), research_repository=object(), experiment_repository=object(), knowledge_base=object(), knowledge_repository=object())
    monkeypatch.setattr("alpha_operator_framework.infrastructure.runtime_factory.build_research_runtime", lambda *_a, **_k: runtime)

    class Rebuilder:
        def __init__(self, *args): assert args == (runtime.event_store, runtime.research_repository, runtime.experiment_repository, runtime.knowledge_base, runtime.knowledge_repository)
        def rebuild(self, round_id): called.append(round_id)

    monkeypatch.setattr("alpha_operator_framework.application.research_rebuild.ResearchProjectionRebuilder", Rebuilder)
    alpha_machine.command_research_rebuild(SimpleNamespace(round_id="r1", config=str(tmp_path / "config.yaml")))

    assert called == ["r1"]


def test_research_cycle_command_uses_new_dry_run_cycle(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **_: [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(f"storage:\n  driver: sqlite\n  path: {tmp_path / 'rounds.db'}\n", encoding="utf-8")
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, datasets=None,
        sample_per_family=1, execute=False, seed=9, config=str(config),
        policy_file=None, telemetry_file=str(tmp_path / "metrics.jsonl"), algorithm="stratified",
    )

    alpha_machine.command_research_cycle(args)

    assert "Research Cycle Summary" in capsys.readouterr().out
    runtime = build_research_runtime(config)
    round_ = runtime.research_repository.load_round("research-GBR-TOP700-9")
    assert [candidate.expression for candidate in round_.candidates] == ["rank(returns)", "ts_rank(returns, 22)"]
    assert EventType.BATCH_ALLOCATED in [
        event.event_type for event in runtime.event_store.read_stream("research-GBR-TOP700-9")
    ]
    assert (tmp_path / "metrics.jsonl").exists()


def test_submission_dispatch_command_is_safe_with_an_empty_outbox(tmp_path, capsys) -> None:
    alpha_machine.command_submission_dispatch(SimpleNamespace(database=str(tmp_path / "rounds.db"), limit=5))

    assert "提交 outbox 已派发: 0" in capsys.readouterr().out


def test_submission_authorization_requires_execute_and_evidence_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("alpha_operator_framework.research.field_loader.load_real_market_fields", lambda **_: [])
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, datasets=None, sample_per_family=1,
        execute=False, seed=9, database=str(tmp_path / "rounds.db"), policy_file=None,
        telemetry_file=None, algorithm="stratified", authorize_submission=True,
        submission_evidence_file=None,
    )

    with pytest.raises(ValueError, match="requires --execute"):
        alpha_machine.command_research_cycle(args)


def test_policy_settings_are_used_when_loading_fields(monkeypatch, tmp_path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        '{"region":"USA","universe":"TOP3000","max_backtests":1,"settings":{"delay":0}}',
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **kwargs: captured.update(kwargs) or [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    args = SimpleNamespace(
        region="USA", universe="TOP3000", delay=None, datasets=None, sample_per_family=1,
        execute=False, seed=9, database=str(tmp_path / "rounds.db"), policy_file=str(policy_path),
        telemetry_file=None, algorithm=None, decay=None, neutralization=None, truncation=None,
    )

    alpha_machine.command_research_cycle(args)

    assert captured == {"region": "USA", "universe": "TOP3000", "delay": 0, "datasets": None}


def test_research_cycle_uses_yaml_defaults_when_cli_options_are_omitted(monkeypatch, tmp_path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        f"storage:\n  driver: sqlite\n  path: {tmp_path / 'rounds.db'}\nresearch:\n  region: USA\n  universe: TOP3000\n  delay: 0\n  sample_per_family: 1\n",
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **kwargs: captured.update(kwargs) or [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    args = SimpleNamespace(
        region=None, universe=None, delay=None, datasets=None, sample_per_family=None,
        execute=False, seed=9, config=str(config), policy_file=None, telemetry_file=None,
        algorithm=None, decay=None, neutralization=None, truncation=None,
    )

    alpha_machine.command_research_cycle(args)

    assert captured == {"region": "USA", "universe": "TOP3000", "delay": 0, "datasets": None}
