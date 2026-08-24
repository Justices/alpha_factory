"""Shared composition root for planning and worker execution."""

from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime


def test_runtime_shares_one_database_backed_event_store_and_projections(tmp_path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    config.write_text(f"storage:\n  driver: sqlite\n  path: {tmp_path / 'research.db'}\n", encoding="utf-8")
    runtime = build_research_runtime(config, execute_platform=False)

    assert runtime.event_store.is_persistent
    assert runtime.research_repository.engine is runtime.experiment_repository.engine
    assert runtime.knowledge_repository.engine is runtime.experiment_repository.engine
    assert runtime.template_repository.engine is runtime.experiment_repository.engine
