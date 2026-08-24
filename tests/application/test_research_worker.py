"""Recovery behavior for the event-led research batch worker."""

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleUseCase
from alpha_operator_framework.application.research_worker import ResearchBatchWorker, ResearchWorkerScheduler
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import EventType
from alpha_operator_framework.experiment.lifecycle import BatchState
from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy


class RoundRepository:
    def save_round(self, round_): self.round = round_
    def load_round(self, _): return self.round


class BatchRepository:
    def __init__(self): self.batch = None
    def load_batch(self, _): return self.batch
    def save_batch(self, batch): self.batch = batch
    def list_due_batches(self): return [self.batch] if self.batch is not None else []


def test_worker_resumes_submitted_batch_and_runs_only_missing_tasks() -> None:
    class Gateway:
        def __init__(self): self.calls = []
        def run_backtests(self, tasks):
            self.calls.append([task.task_id for task in tasks])
            return [BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, f"alpha-{task.task_id}") for task in tasks]

    events, rounds, batches, knowledge, gateway = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase(), Gateway()
    request = ResearchCycleRequest(
        "worker-round", 9, ResearchPolicy("GBR", "TOP700", 2), KnowledgeSnapshot(version=0),
        [
            Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template"),
            Candidate("b", "rank(open)", "family", ("open",), ("rank",), "template"),
        ], True,
    )
    ResearchCycleUseCase(rounds, gateway, knowledge, batches, event_store=events).execute(request)
    completed_task = next(iter(batches.batch.tasks.values()))
    batches.batch.record_result(BacktestResult(completed_task.task_id, completed_task.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-existing"))
    batches.save_batch(batches.batch)

    summary = ResearchBatchWorker(events, rounds, batches, knowledge, gateway).process_round("worker-round")

    assert summary.status == "COMPLETED"
    assert gateway.calls == [["worker-round:1"]]
    assert batches.batch.state is BatchState.EVALUATED
    assert EventType.SIMULATION_COMPLETED in [event.event_type for event in events.read_stream("worker-round")]


def test_worker_persists_distilled_template_promotions() -> None:
    class Gateway:
        def run_backtests(self, tasks):
            return [BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1") for task in tasks]

    class TemplateRepository:
        def __init__(self): self.promoted = []
        def promote(self, templates): self.promoted.extend(templates)

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    ResearchCycleUseCase(rounds, Gateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "promotion-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
            [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )
    promotions = TemplateRepository()

    ResearchBatchWorker(events, rounds, batches, knowledge, Gateway(), template_repository=promotions).process_round("promotion-round")

    assert [template.expression_template for template in promotions.promoted] == ["rank({a})"]
    assert EventType.TEMPLATE_PROMOTED in [event.event_type for event in events.read_stream("promotion-round")]


def test_worker_persists_retry_state_after_rate_limit() -> None:
    class RateLimitedGateway:
        def run_backtests(self, _tasks):
            raise TimeoutError("429 rate limited")

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    ResearchCycleUseCase(rounds, RateLimitedGateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "retry-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
            [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )

    summary = ResearchBatchWorker(events, rounds, batches, knowledge, RateLimitedGateway()).process_round("retry-round")

    task = next(iter(batches.batch.tasks.values()))
    assert summary.status == "RETRY_SCHEDULED"
    assert task.attempts == 1
    assert task.next_retry_at is not None
    assert task.last_error == "429 rate limited"


def test_worker_scans_and_processes_due_batches() -> None:
    class Gateway:
        def run_backtests(self, tasks):
            return [BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1") for task in tasks]

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    ResearchCycleUseCase(rounds, Gateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "due-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
            [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )

    summaries = ResearchBatchWorker(events, rounds, batches, knowledge, Gateway()).process_due_batches()

    assert [(summary.round_id, summary.status) for summary in summaries] == [("due-round", "COMPLETED")]


def test_cycle_records_complete_candidate_facts_for_rebuild() -> None:
    events, rounds, batches = EventStore(), RoundRepository(), BatchRepository()
    candidate = Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")
    ResearchCycleUseCase(rounds, object(), KnowledgeBase(), batches, event_store=events).execute(
        ResearchCycleRequest("facts-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0), [candidate], False)
    )

    payload = next(event.payload for event in events.read_stream("facts-round") if event.event_type is EventType.CANDIDATE_GENERATED)

    assert tuple(payload["candidate"]["fields"]) == ("close",)


def test_scheduler_watches_due_batches_at_a_configured_interval() -> None:
    class Worker:
        def __init__(self): self.calls = 0
        def process_due_batches(self):
            self.calls += 1
            return ["done"]

    pauses = []
    completed = ResearchWorkerScheduler(Worker()).watch(poll_seconds=7, sleep=pauses.append, max_cycles=2)

    assert completed == ["done", "done"]
    assert pauses == [7]
