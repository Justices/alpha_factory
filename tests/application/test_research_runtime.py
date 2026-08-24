"""Shared composition root for planning and worker execution."""

from alpha_operator_framework.application.research_runtime import ResearchRuntime


def test_runtime_shares_one_database_backed_event_store_and_projections(tmp_path) -> None:
    runtime = ResearchRuntime.create(tmp_path / "research.db", execute_platform=False)

    assert runtime.event_store.is_persistent
    assert runtime.research_repository.path == runtime.experiment_repository.path
    assert runtime.knowledge_repository.path == runtime.experiment_repository.path
    assert runtime.template_repository.path == runtime.experiment_repository.path
