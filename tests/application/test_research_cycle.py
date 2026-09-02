"""Application composition tests for the new research-round cycle."""

from __future__ import annotations

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleUseCase
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.experiment.models import BacktestResult, ExperimentBatch
from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.infrastructure.brain import DryRunGateway
from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import SqlAlchemyExperimentRepository
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.infrastructure.telemetry import ResearchTelemetry
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy


class MemoryRepository:
    def __init__(self) -> None:
        self.round = None

    def save_round(self, round_) -> None:
        self.round = round_


class MemoryBatchRepository:
    def __init__(self, batch=None) -> None:
        self.batch = batch

    def load_batch(self, _): return self.batch
    def save_batch(self, batch): self.batch = batch


class RecordingAlphaRepository:
    def __init__(self) -> None:
        self.inserted = []
        self.created_batches = []

    def insert_expression(self, expression, settings, **kwargs) -> None:
        self.inserted.append((expression, settings, kwargs))

    def catalog_research_candidates(self, *_args, **_kwargs) -> None:
        return None

    def record_round_selection(self, *_args, **_kwargs) -> None:
        return None

    def compute_alpha_sha(self, expression, _settings): return expression
    def mark_expressions_pruned(self, *_args, **_kwargs) -> None: return None
    def mark_round_candidates_pruned(self, *_args, **_kwargs) -> None: return None

    def create_simulation_batch(self, tasks, settings, **kwargs) -> int:
        self.created_batches.append((tasks, settings, kwargs))
        return 17


def test_runtime_close_releases_primary_repository_and_sqlalchemy_engine() -> None:
    from alpha_operator_framework.application.research_runtime import ResearchRuntime

    class CloseableRepository:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Engine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    repository, engine = CloseableRepository(), Engine()
    runtime = ResearchRuntime(None, None, None, None, None, None, None, alpha_database=repository, engine=engine)

    runtime.close()

    assert repository.closed is True
    assert engine.disposed is True


def test_cycle_returns_replayable_planned_round_without_live_gateway() -> None:
    repository = MemoryRepository()
    use_case = ResearchCycleUseCase(repository, DryRunGateway())
    request = ResearchCycleRequest(
        round_id="round-1",
        seed=9,
        policy=ResearchPolicy("GBR", "TOP700", 1),
        knowledge=KnowledgeSnapshot(version=0),
        candidates=[Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        execute_platform=False,
        catalog_round_id="round-1",
    )

    summary = use_case.execute(request)

    assert summary.status == "PLANNED"
    assert summary.selection_audit
    assert repository.round.round_id == "round-1"


def test_live_cycle_does_not_create_an_empty_batch_when_all_candidates_are_rejected() -> None:
    class RejectingKnowledge(KnowledgeSnapshot):
        def rejects(self, _candidate) -> bool:
            return True

    class RootCatalogRepository:
        def __init__(self) -> None:
            self.pruned_round_ids = []
        def insert_expression(self, *_args, **_kwargs) -> None: return None
        def record_round_selection(self, *_args, **_kwargs) -> None: return None
        def prune_unselected_round_candidates(self, round_id) -> None:
            self.pruned_round_ids.append(round_id)

    repository = MemoryRepository()
    batches = MemoryBatchRepository()
    primary = RootCatalogRepository()
    summary = ResearchCycleUseCase(
        repository, DryRunGateway(), RejectingKnowledge(version=0), batches, event_store=EventStore(), alpha_database=primary,
    ).execute(ResearchCycleRequest(
        "empty-live-round", 9, ResearchPolicy("GBR", "TOP700", 1),
        RejectingKnowledge(version=0),
        [Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        True,
        catalog_round_id="empty-live-round",
    ))

    assert summary.status == "NO_ELIGIBLE_CANDIDATES"
    assert batches.batch is None
    assert primary.pruned_round_ids == ["empty-live-round"]


def test_planned_cycle_catalogs_every_candidate_before_selection() -> None:
    primary = RecordingAlphaRepository()
    candidates = [
        Candidate("first", "rank(close)", "family", ("close",), ("rank",), "template"),
        Candidate("second", "rank(volume)", "family", ("volume",), ("rank",), "template"),
    ]

    ResearchCycleUseCase(MemoryRepository(), DryRunGateway(), alpha_database=primary).execute(
        ResearchCycleRequest("catalog-planned", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0), candidates, catalog_round_id="catalog-planned")
    )

    assert [expression for expression, _, _ in primary.inserted] == ["rank(close)", "rank(volume)"]


def test_live_cycle_defers_static_pruning_until_after_backtesting() -> None:
    batches = MemoryBatchRepository()
    candidate = Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")

    ResearchCycleUseCase(MemoryRepository(), CompletedGateway(), KnowledgeBase(), batches, event_store=EventStore()).execute(
        ResearchCycleRequest(
            "deferred-pruning", 9,
            ResearchPolicy("GBR", "TOP700", 1, prohibited_patterns=("rank(",)),
            KnowledgeSnapshot(version=0), [candidate], True,
            catalog_round_id="deferred-pruning",
        )
    )

    assert [task.candidate_id for task in batches.batch.tasks.values()] == ["candidate"]


def test_live_cycle_records_selection_on_root_catalog_and_batch_on_child_round() -> None:
    class LinkedPrimaryRepository:
        def __init__(self):
            self.cataloged, self.selections, self.batch_round_id = [], [], None
        def insert_expression(self, *_args, **_kwargs): return 1
        def catalog_research_candidates(self, round_id, candidates, settings): self.cataloged.append((round_id, candidates, settings))
        def record_round_selection(self, round_id, decisions): self.selections.append((round_id, decisions))
        def create_simulation_batch(self, _tasks, _settings, **kwargs):
            self.batch_round_id = kwargs.get("round_id")
            return 17

    primary, batches = LinkedPrimaryRepository(), MemoryBatchRepository()
    candidates = [
        Candidate("first", "rank(close)", "family", ("close",), ("rank",), "template"),
        Candidate("second", "rank(volume)", "family", ("volume",), ("rank",), "template"),
    ]
    ResearchCycleUseCase(MemoryRepository(), CompletedGateway(), KnowledgeBase(), batches, event_store=EventStore(), alpha_database=primary).execute(
        ResearchCycleRequest(
            "linked-root-batch-1", 9, ResearchPolicy("GBR", "TOP700", 1),
            KnowledgeSnapshot(version=0), candidates, True,
            catalog_round_id="linked-root",
        )
    )

    assert primary.cataloged == []
    assert primary.selections[0][0] == "linked-root"
    assert primary.batch_round_id == "linked-root-batch-1"


class CompletedGateway:
    def run_backtests(self, tasks):
        return [BacktestResult(tasks[0].task_id, tasks[0].expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")]


def test_execute_cycle_submits_a_recoverable_batch_without_running_gateway() -> None:
    class CountingGateway:
        calls = 0

        def run_backtests(self, tasks):
            self.calls += 1
            return []

    gateway = CountingGateway()
    batches = MemoryBatchRepository()
    summary = ResearchCycleUseCase(MemoryRepository(), gateway, KnowledgeBase(), batches, event_store=EventStore()).execute(
        ResearchCycleRequest(
            "round-submitted", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
            [Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")], True,
            catalog_round_id="round-submitted",
        )
    )

    assert summary.status == "SUBMITTED"
    assert gateway.calls == 0
    assert batches.batch.state is BatchState.SUBMITTED


def test_execute_cycle_catalogs_all_candidates_and_binds_selected_tasks_to_a_real_batch() -> None:
    primary = RecordingAlphaRepository()
    batches = MemoryBatchRepository()
    candidates = [
        Candidate("first", "rank(close)", "family", ("close",), ("rank",), "template"),
        Candidate("second", "rank(volume)", "family", ("volume",), ("rank",), "template"),
    ]
    ResearchCycleUseCase(MemoryRepository(), CompletedGateway(), KnowledgeBase(), batches, event_store=EventStore(), alpha_database=primary).execute(
        ResearchCycleRequest("primary-store-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0), candidates, True, catalog_round_id="primary-store-round")
    )

    settings = {"region": "GBR", "universe": "TOP700", "delay": 1, "decay": 8, "neutralization": "SUBINDUSTRY", "truncation": 0.08}
    assert [expression for expression, _, _ in primary.inserted] == ["rank(close)", "rank(volume)"]
    assert all(value == settings for _, value, _ in primary.inserted)
    assert primary.created_batches == [(
        [{"task_id": "primary-store-round:0", "candidate_id": "first", "expression": "rank(close)"}],
        settings,
        {"simulation_type": "RESEARCH", "round_id": "primary-store-round"},
    )]
    assert batches.batch.storage_batch_id == 17


def test_execute_cycle_requires_event_ledger_and_batch_projection() -> None:
    request = ResearchCycleRequest(
        "invalid-live-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
        [Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        catalog_round_id="invalid-live-round",
    )

    import pytest

    with pytest.raises(ValueError, match="event store and experiment repository"):
        ResearchCycleUseCase(MemoryRepository(), CompletedGateway()).execute(request)


def test_planner_reuses_partial_failed_batch_without_recreating_tasks() -> None:
    policy = ResearchPolicy("GBR", "TOP700", 1)
    candidate = Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")
    batch = ExperimentBatch("partial-round", "persisted-key")
    original = batch.create_tasks([candidate], policy)[0]
    transition(batch, BatchState.SUBMITTED); transition(batch, BatchState.RUNNING); transition(batch, BatchState.PARTIAL_FAILED)
    batches = MemoryBatchRepository(batch)

    ResearchCycleUseCase(MemoryRepository(), CompletedGateway(), KnowledgeBase(), batches, event_store=EventStore()).execute(
        ResearchCycleRequest("partial-round", 9, policy, KnowledgeSnapshot(version=0), [candidate], True, catalog_round_id="partial-round")
    )

    assert batches.batch.state is BatchState.PARTIAL_FAILED
    assert list(batches.batch.tasks) == [original.task_id]


def test_live_cycle_only_submits_work_for_the_worker() -> None:
    repository = MemoryRepository()
    knowledge_base = KnowledgeBase()
    use_case = ResearchCycleUseCase(repository, CompletedGateway(), knowledge_base, MemoryBatchRepository(), event_store=EventStore())
    request = ResearchCycleRequest(
        round_id="round-live",
        seed=9,
        policy=ResearchPolicy("GBR", "TOP700", 1),
        knowledge=knowledge_base.snapshot(),
        candidates=[Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        execute_platform=True,
        catalog_round_id="round-live",
    )

    summary = use_case.execute(request)

    assert summary.status == "SUBMITTED"
    assert summary.completed_backtests == 0
    assert knowledge_base.field_scores == {}


def test_live_cycle_persists_submitted_batch(tmp_path) -> None:
    repository = MemoryRepository()
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "rounds.db"}, base_path=tmp_path)); migrate(engine)
    experiment_repository = SqlAlchemyExperimentRepository(engine)
    use_case = ResearchCycleUseCase(repository, CompletedGateway(), KnowledgeBase(), experiment_repository, event_store=EventStore())
    request = ResearchCycleRequest(
        round_id="round-persisted", seed=9,
        policy=ResearchPolicy("GBR", "TOP700", 1), knowledge=KnowledgeSnapshot(version=0),
        candidates=[Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        execute_platform=True,
        catalog_round_id="round-persisted",
    )

    use_case.execute(request)

    batch = experiment_repository.load_batch("round-persisted")
    assert batch.state == BatchState.SUBMITTED
    assert [entry.to_state for entry in batch.transitions][-1] == BatchState.SUBMITTED


def test_live_cycle_records_operational_telemetry() -> None:
    telemetry = ResearchTelemetry()
    use_case = ResearchCycleUseCase(
        MemoryRepository(), CompletedGateway(), KnowledgeBase(), MemoryBatchRepository(), telemetry, EventStore(),
    )
    request = ResearchCycleRequest(
        round_id="round-metrics", seed=9, policy=ResearchPolicy("GBR", "TOP700", 1),
        knowledge=KnowledgeSnapshot(version=0),
        candidates=[Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        execute_platform=True,
        catalog_round_id="round-metrics",
    )

    use_case.execute(request)

    metrics = telemetry.snapshot()
    assert metrics["batch_transitions"]["SUBMITTED"] == 1
    assert metrics["backtests_completed"] == 0


def test_live_cycle_resumes_existing_submitted_batch() -> None:
    class BatchRepository:
        def __init__(self, batch): self.batch = batch
        def load_batch(self, _): return self.batch
        def save_batch(self, batch): self.batch = batch
    policy = ResearchPolicy("GBR", "TOP700", 1)
    candidate = Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")
    existing = ExperimentBatch("round-resume", "persisted-key")
    task = existing.create_tasks([candidate], policy)[0]
    transition(existing, BatchState.SUBMITTED)
    repository = BatchRepository(existing)
    use_case = ResearchCycleUseCase(MemoryRepository(), CompletedGateway(), KnowledgeBase(), repository, event_store=EventStore())

    use_case.execute(ResearchCycleRequest("round-resume", 9, policy, KnowledgeSnapshot(version=0), [candidate], True, catalog_round_id="round-resume"))

    assert repository.batch.tasks[task.task_id].idempotency_key == task.idempotency_key
    assert repository.batch.state == BatchState.SUBMITTED
