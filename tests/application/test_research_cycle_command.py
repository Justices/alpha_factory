"""CLI composition tests for the new research-cycle entry point."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import alpha_machine
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import EventType
from alpha_operator_framework.infrastructure.sqlite import SqliteResearchRepository


def test_research_cycle_command_uses_new_dry_run_cycle(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **_: [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, datasets=None,
        sample_per_family=1, execute=False, seed=9, database=str(tmp_path / "rounds.db"),
        policy_file=None, telemetry_file=str(tmp_path / "metrics.jsonl"), algorithm="stratified",
    )

    alpha_machine.command_research_cycle(args)

    assert "Research Cycle Summary" in capsys.readouterr().out
    round_ = SqliteResearchRepository(tmp_path / "rounds.db").load_round("research-GBR-TOP700-9")
    assert [candidate.expression for candidate in round_.candidates] == ["rank(returns)", "ts_rank(returns, 22)"]
    assert EventType.BATCH_ALLOCATED in [
        event.event_type for event in EventStore(db_path=tmp_path / "rounds.db").read_stream("research-GBR-TOP700-9")
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
