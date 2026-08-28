"""Composition-root boundary tests."""

from pathlib import Path

import pytest

from alpha_operator_framework.infrastructure.runtime_factory import (
    build_research_runtime,
    resolve_construction_plan,
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
