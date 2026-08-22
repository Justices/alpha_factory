"""CLI composition tests for the new research-cycle entry point."""

from __future__ import annotations

from types import SimpleNamespace

import alpha_machine
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.infrastructure.sqlite import SqliteResearchRepository


def test_research_cycle_command_uses_new_dry_run_cycle(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **_: [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, datasets=None,
        sample_per_family=1, execute=False, seed=9, database=str(tmp_path / "rounds.db"),
    )

    alpha_machine.command_research_cycle(args)

    assert '"status": "PLANNED"' in capsys.readouterr().out
    round_ = SqliteResearchRepository(tmp_path / "rounds.db").load_round("research-GBR-TOP700-9")
    assert [candidate.expression for candidate in round_.candidates] == ["rank(returns)", "ts_rank(returns, 22)"]
