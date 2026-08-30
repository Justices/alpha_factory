"""CLI composition tests for the new research-cycle entry point."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import alpha_operator_framework.cli.research as alpha_machine
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.core.events import EventType
from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime


def _config(tmp_path):
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        f"""storage:
  driver: sqlite
  path: {tmp_path / 'rounds.db'}
research:
  region: GBR
  universe: TOP700
  delay: 1
  construction:
    strategies:
      - id: database
        kind: database_template
        families: ["*"]
        order_depth: {{min: 0, max: 12}}
        field_count: {{min: 1, max: 4}}
        quota_per_leaf_family: 8
        source: raw_fields
    platform_batch_size: 8
""",
        encoding="utf-8",
    )
    return config


def _cache_universes(monkeypatch, tmp_path, region: str, delay: int, universes: list[str]) -> None:
    index = tmp_path / region / str(delay) / "universe.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps(universes), encoding="utf-8")
    monkeypatch.setattr("alpha_operator_framework.research.field_loader.DATAFIELDS_DIR", tmp_path)


def test_default_round_id_is_unique_but_explicit_round_id_is_reusable(monkeypatch) -> None:
    monkeypatch.setattr(alpha_machine, "uuid4", lambda: SimpleNamespace(hex="unique-token"))
    policy = SimpleNamespace(region="EUR", universe="TOP2500")

    assert alpha_machine._round_id(SimpleNamespace(round_id=None), policy, {"seed": 42}) == "research-EUR-TOP2500-42-unique-t"
    assert alpha_machine._round_id(SimpleNamespace(round_id="resume-me"), policy, {"seed": 42}) == "resume-me"


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
    config = _config(tmp_path)
    _cache_universes(monkeypatch, tmp_path, "GBR", 1, ["TOP700"])
    args = SimpleNamespace(
            region="GBR", universe="TOP700", delay=1, datasets=None,
            execute=False, seed=9, config=str(config),
            policy_file=None, telemetry_file=str(tmp_path / "metrics.jsonl"), algorithm="stratified", round_id="test-round",
    )

    alpha_machine.command_research_cycle(args)

    assert "Research Cycle Summary" in capsys.readouterr().out
    runtime = build_research_runtime(config)
    round_ = runtime.research_repository.load_round("test-round")
    assert {candidate.family.split("/")[1] for candidate in round_.candidates} == {"unary"}
    assert all("vector_neut" not in candidate.expression for candidate in round_.candidates)
    assert EventType.BATCH_ALLOCATED in [
        event.event_type for event in runtime.event_store.read_stream("test-round")
    ]
    assert (tmp_path / "metrics.jsonl").exists()


def test_research_cycle_sets_the_requested_quota_for_each_family(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **_: [
            FieldSpec(id="returns", dataset_id="pv1", type="MATRIX"),
            FieldSpec(id="volume", dataset_id="pv1", type="MATRIX"),
            FieldSpec(id="close", dataset_id="pv1", type="MATRIX"),
        ],
    )
    config = _config(tmp_path)
    _cache_universes(monkeypatch, tmp_path, "GBR", 1, ["TOP700"])
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, datasets=None,
        execute=False, seed=9, config=str(config),
        policy_file=None, telemetry_file=None, algorithm="stratified", round_id="quota-round",
    )

    alpha_machine.command_research_cycle(args)

    runtime = build_research_runtime(config)
    policy = runtime.research_repository.load_round("quota-round").policy
    assert policy.family_quotas
    assert set(policy.family_quotas.values()) == {8}
    assert all(family.startswith("database_template/") for family in policy.family_quotas)
    assert policy.max_backtests == sum(policy.family_quotas.values())


def test_submission_dispatch_command_is_safe_with_an_empty_outbox(tmp_path, capsys) -> None:
    alpha_machine.command_submission_dispatch(SimpleNamespace(config=str(_config(tmp_path)), limit=5, max_attempts=3))

    assert "提交 outbox 已派发: 0" in capsys.readouterr().out


def test_submission_authorization_requires_execute_and_evidence_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("alpha_operator_framework.research.field_loader.load_real_market_fields", lambda **_: [])
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, datasets=None,
        execute=False, seed=9, config=str(_config(tmp_path)), policy_file=None,
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
    _cache_universes(monkeypatch, tmp_path, "USA", 0, ["TOP3000"])
    args = SimpleNamespace(
        region="USA", universe="TOP3000", delay=None, datasets=None,
        execute=False, seed=9, config=str(_config(tmp_path)), policy_file=str(policy_path),
        telemetry_file=None, algorithm=None, decay=None, neutralization=None, truncation=None,
    )

    alpha_machine.command_research_cycle(args)

    assert captured == {"region": "USA", "universe": "TOP3000", "delay": 0, "datasets": None,
                        "include_base_fields": False, "allow_scope_fallback": False, "category": None}


def test_research_cycle_uses_yaml_defaults_when_cli_options_are_omitted(monkeypatch, tmp_path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        f"""storage:
  driver: sqlite
  path: {tmp_path / 'rounds.db'}
research:
  region: USA
  universe: TOP3000
  delay: 0
  construction:
    strategies:
      - id: database
        kind: database_template
        families: ["*"]
        order_depth: {{min: 0, max: 12}}
        field_count: {{min: 1, max: 4}}
        quota_per_leaf_family: 8
        source: raw_fields
    platform_batch_size: 8
""",
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **kwargs: captured.update(kwargs) or [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    _cache_universes(monkeypatch, tmp_path, "USA", 0, ["TOP500", "TOP3000"])
    args = SimpleNamespace(
        region=None, universe=None, delay=None, datasets=None,
        execute=False, seed=9, config=str(config), policy_file=None, telemetry_file=None,
        algorithm=None, decay=None, neutralization=None, truncation=None,
    )

    alpha_machine.command_research_cycle(args)

    assert captured == {"region": "USA", "universe": "TOP500", "delay": 0, "datasets": None,
                        "include_base_fields": False, "allow_scope_fallback": False, "category": None}


def test_continue_research_delegates_to_the_closed_loop(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        "alpha_operator_framework.research.field_loader.load_real_market_fields",
        lambda **_: [FieldSpec(id="returns", dataset_id="pv1", type="MATRIX")],
    )
    _cache_universes(monkeypatch, tmp_path, "GBR", 1, ["TOP700"])
    calls = []

    class Coordinator:
        def __init__(self, runtime):
            self.runtime = runtime

        def run(self, policy, fields, candidates, *, construction_plan, seed, execute, base_round_id, strategy_statuses):
            calls.append((policy, fields, candidates, seed, execute, base_round_id))
            return SimpleNamespace(status="EXHAUSTED", round_ids=[base_round_id], completed_backtests=24)

    class Database:
        def construction_task_exists(self, _task_id):
            return True

        def requeue_retryable_failed_research_expressions(self, _settings):
            return 0

        def load_unbacktested_research_candidates(self, _settings):
            return []

        def load_construction_strategy_statuses(self, _task_id):
            return []

        def list_templates(self, *, active_only=True):
            return [Template(name="rank", family="unary", expression_template="rank({a})", slot_count=1)]

    runtime = SimpleNamespace(
        alpha_database=Database(), knowledge_base=SimpleNamespace(snapshot=lambda: None), telemetry=None,
        plan=lambda _request: (_ for _ in ()).throw(AssertionError("CLI must delegate continuous execution")),
    )
    monkeypatch.setattr("alpha_operator_framework.infrastructure.runtime_factory.build_research_runtime", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr("alpha_operator_framework.application.research_loop.ResearchLoopCoordinator", Coordinator)
    args = SimpleNamespace(
        region="GBR", universe="TOP700", delay=1, decay=None, neutralization=None, truncation=None,
        datasets=None, category=None, execute=True, continue_research=True,
        seed=9, config=str(_config(tmp_path)), policy_file=None, telemetry_file=None,
        algorithm="stratified", round_id="loop-round", authorize_submission=False,
        submission_evidence_file=None,
    )

    alpha_machine.command_research_cycle(args)

    assert len(calls) == 1
    assert calls[0][-1] == "loop-round"
    assert "loop-round | EXHAUSTED | backtests=24" in capsys.readouterr().out
