"""Composition-root boundary tests."""

from pathlib import Path

from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime


def test_runtime_factory_builds_driver_neutral_adapters_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    database = tmp_path / "research.db"
    config.write_text(
        "storage:\n  driver: sqlite\n  path: " + database.as_posix() + "\nresearch:\n  execute_platform: false\n",
        encoding="utf-8",
    )

    runtime = build_research_runtime(config)

    assert Path(runtime.experiment_repository.engine.url.database).resolve() == database.resolve()
    assert runtime.event_store.db_path == "persistent"


def test_application_runtime_does_not_import_sqlite_adapter() -> None:
    source = (Path(__file__).parents[2] / "alpha_operator_framework" / "application" / "research_runtime.py").read_text(encoding="utf-8")
    factory_source = (Path(__file__).parents[2] / "alpha_operator_framework" / "infrastructure" / "runtime_factory.py").read_text(encoding="utf-8")

    assert "infrastructure.sqlite" not in source
    assert "EventStore" not in source
    assert "infrastructure.sqlite" not in factory_source
    assert "AlphaDatabase" not in factory_source
