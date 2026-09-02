"""Composition-root boundary tests."""

from pathlib import Path

import pytest

from alpha_operator_framework.infrastructure.runtime_factory import (
    build_research_runtime,
    resolve_construction_plan,
    resolve_literature_llm_options,
)


def test_runtime_factory_builds_driver_neutral_adapters_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    database = tmp_path / "research.db"
    config.write_text(
        "storage:\n  driver: sqlite\n  path: " + database.as_posix() + "\nresearch:\n  execute_platform: false\n",
        encoding="utf-8",
    )

    runtime = build_research_runtime(config)

    assert Path(runtime.experiment_repository.engine.url.database).resolve() == database.resolve()
    assert runtime.event_store.is_persistent is True


def test_application_runtime_does_not_import_sqlite_adapter() -> None:
    source = (Path(__file__).parents[2] / "alpha_operator_framework" / "application" / "research_runtime.py").read_text(encoding="utf-8")
    factory_source = (Path(__file__).parents[2] / "alpha_operator_framework" / "infrastructure" / "runtime_factory.py").read_text(encoding="utf-8")

    assert "infrastructure.sqlite" not in source
    assert "EventStore" not in source
    assert "infrastructure.sqlite" not in factory_source


def test_runtime_factory_resolves_required_explicit_construction_plan(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        f"""storage:
  driver: sqlite
  path: {(tmp_path / 'research.db').as_posix()}
research:
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

    plan = resolve_construction_plan(config)

    assert [strategy.strategy_id for strategy in plan.strategies] == ["database"]


def test_runtime_factory_rejects_missing_construction_plan_before_execution(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        f"storage:\n  driver: sqlite\n  path: {(tmp_path / 'research.db').as_posix()}\nresearch: {{}}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit strategy configuration is required"):
        resolve_construction_plan(config)


def test_runtime_factory_resolves_named_ordered_construction_mode(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        f"""storage:
  driver: sqlite
  path: {(tmp_path / 'research.db').as_posix()}
research:
  default_construction_mode: multi-stage
  construction_modes:
    multi-stage:
      stages:
        - [first]
        - [second]
  construction:
    strategies:
      - id: first
        kind: raw_first_order
        families: ["first_order"]
        order_depth: {{min: 1, max: 3}}
        field_count: {{exact: 1}}
        source: raw_fields
      - id: second
        kind: depth_construction
        families: ["unary"]
        order_depth: {{min: 2, max: 6}}
        field_count: {{min: 1, max: 2}}
        source: qualified_candidates
""",
        encoding="utf-8",
    )

    plan = resolve_construction_plan(config)

    assert [(strategy.strategy_id, strategy.stage) for strategy in plan.strategies] == [
        ("first", 1), ("second", 2),
    ]


def test_checked_in_construction_modes_keep_their_intended_stage_graph() -> None:
    config = Path(__file__).parents[2] / "configs" / "alpha-factory.yaml"

    resolved = {
        mode: [(strategy.strategy_id, strategy.stage) for strategy in resolve_construction_plan(config, mode=mode).strategies]
        for mode in ("template", "multi-stage", "ai-multi-stage", "multivariate")
    }

    assert resolved == {
        "template": [("database-template", 1)],
        "multi-stage": [
            ("raw-first-order", 1), ("qualified-depth", 2),
            ("qualified-group-second-order", 3), ("signal-validation", 4),
        ],
        "ai-multi-stage": [
            ("ai-naked-signals", 1), ("qualified-depth", 2),
            ("qualified-group-second-order", 3), ("signal-validation", 4),
        ],
        "multivariate": [
            ("raw-first-order", 1), ("qualified-composition", 2),
            ("signal-validation", 3),
        ],
    }


def test_literature_llm_options_merge_yaml_and_explicit_cli_values(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(
        "storage:\n  driver: sqlite\n  path: research.db\nresearch:\n"
        "  literature_llm:\n    enabled: true\n    config_path: llm/default.json\n"
        "    provider: qwen\n    model: qwen-plus\n",
        encoding="utf-8",
    )

    configured = resolve_literature_llm_options(config, {})
    overridden = resolve_literature_llm_options(config, {
        "enabled": False,
        "config_path": "llm/override.json",
        "provider": "openai",
        "model": "gpt-4o",
    })

    assert configured == {
        "enabled": True,
        "config_path": (tmp_path / "llm" / "default.json").resolve(),
        "provider": "qwen",
        "model": "qwen-plus",
    }
    assert overridden == {
        "enabled": False,
        "config_path": (tmp_path / "llm" / "override.json").resolve(),
        "provider": "openai",
        "model": "gpt-4o",
    }
