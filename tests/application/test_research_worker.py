"""Recovery behavior for the event-led research batch worker."""

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleUseCase
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from alpha_operator_framework.application.research_worker import ResearchBatchWorker, ResearchWorkerScheduler
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.experiment.lifecycle import BatchState
from alpha_operator_framework.experiment.models import BacktestResult, BacktestTask, ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy, ResearchRound


class RoundRepository:
    def save_round(self, round_): self.round = round_
    def load_round(self, _): return self.round


class BatchRepository:
    def __init__(self): self.batch = None
    def load_batch(self, _): return self.batch
    def save_batch(self, batch): self.batch = batch
    def list_due_batches(self): return [self.batch] if self.batch is not None else []


def test_worker_does_not_prune_backtested_expressions() -> None:
    class Gateway:
        def run_backtests(self, tasks):
            return [BacktestResult(task.task_id, task.expression, -0.1, 0.2, 0.2, 1.0, False, "alpha-1") for task in tasks]

    class PrimaryStore:
        def __init__(self): self.pruned = []
        def insert_expression(self, *_args, **_kwargs): return 1
        def catalog_research_candidates(self, *_args, **_kwargs): return None
        def record_round_selection(self, *_args, **_kwargs): return None
        def create_simulation_batch(self, *_args, **_kwargs): return 1
        def record_simulation_result(self, *_args, **_kwargs): return None
        def save_result_with_checks(self, *_args, **_kwargs): return None
        def set_expression_status(self, *_args, **_kwargs): return None
        @staticmethod
        def compute_alpha_sha(expression, settings): return f"alpha:{expression}:{settings['region']}"
        def mark_expressions_pruned(self, shas): self.pruned.extend(shas)
        def mark_round_candidates_pruned(self, *_args, **_kwargs): return None
        def prune_unselected_round_candidates(self, *_args, **_kwargs): return None

    events, rounds, batches, knowledge, primary = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase(), PrimaryStore()
    ResearchCycleUseCase(rounds, Gateway(), knowledge, batches, event_store=events, alpha_database=primary).execute(
        ResearchCycleRequest(
            "pruned-after-result", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
            [Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )

    ResearchBatchWorker(events, rounds, batches, knowledge, Gateway(), alpha_database=primary).process_round("pruned-after-result")

    assert primary.pruned == []


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


def test_worker_submits_selected_tasks_in_batches_of_eight() -> None:
    class Gateway:
        def __init__(self): self.calls = []
        def run_backtests(self, tasks):
            self.calls.append(len(tasks))
            return [BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, f"alpha-{task.task_id}") for task in tasks]

    events, rounds, batches, knowledge, gateway = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase(), Gateway()
    candidates = [
        Candidate(str(index), f"rank(field_{index})", "family", (f"field_{index}",), ("rank",), "template")
        for index in range(17)
    ]
    ResearchCycleUseCase(rounds, gateway, knowledge, batches, event_store=events).execute(
        ResearchCycleRequest("chunked-round", 9, ResearchPolicy("GBR", "TOP700", 17), KnowledgeSnapshot(version=0), candidates, True)
    )

    summary = ResearchBatchWorker(events, rounds, batches, knowledge, gateway).process_round("chunked-round")

    assert gateway.calls == [8, 8, 1]
    assert summary.status == "COMPLETED"


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


def test_worker_projects_distilled_templates_to_primary_library() -> None:
    class Gateway:
        def run_backtests(self, tasks):
            return [BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1") for task in tasks]

    class PrimaryStore:
        def __init__(self): self.templates = []
        def insert_expression(self, *_args, **_kwargs): return 1
        def catalog_research_candidates(self, *_args, **_kwargs): return None
        def record_round_selection(self, *_args, **_kwargs): return None
        def create_simulation_batch(self, *_args, **_kwargs): return 1
        def record_simulation_result(self, *_args, **_kwargs): return None
        def save_result_with_checks(self, *_args, **_kwargs): return None
        def set_expression_status(self, *_args, **_kwargs): return None
        def save_abstracted_template(self, **kwargs): self.templates.append(kwargs); return True
        def prune_unselected_round_candidates(self, *_args, **_kwargs): return None

    events, rounds, batches, knowledge, primary = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase(), PrimaryStore()
    ResearchCycleUseCase(rounds, Gateway(), knowledge, batches, event_store=events, alpha_database=primary).execute(
        ResearchCycleRequest("primary-promotion-round", 9, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
                             [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True)
    )

    ResearchBatchWorker(events, rounds, batches, knowledge, Gateway(), alpha_database=primary).process_round("primary-promotion-round")

    assert primary.templates == [{
        "expression_template": "rank({a})", "support_count": 1, "example_expression": "rank(close)",
    }]


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
    retry_event = next(event for event in events.read_stream("retry-round") if "retry" in event.payload)
    assert retry_event.payload["retry"]["state"] == "PARTIAL_FAILED"
    assert retry_event.payload["retry"]["tasks"] == [{
        "task_id": task.task_id, "attempts": 1, "next_retry_at": task.next_retry_at,
        "last_error": "429 rate limited",
    }]


def test_worker_records_outstanding_tasks_when_gateway_returns_partial_results() -> None:
    class PartialGateway:
        def run_backtests(self, tasks):
            task = tasks[0]
            return [BacktestResult(task.task_id, task.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")]

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    ResearchCycleUseCase(rounds, PartialGateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "partial-result-round", 9, ResearchPolicy("GBR", "TOP700", 2), KnowledgeSnapshot(version=0),
            [
                Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template"),
                Candidate("b", "rank(open)", "family", ("open",), ("rank",), "template"),
            ], True,
        )
    )

    ResearchBatchWorker(events, rounds, batches, knowledge, PartialGateway()).process_round("partial-result-round")

    outstanding = batches.batch.tasks["partial-result-round:1"]
    retry_event = next(event for event in events.read_stream("partial-result-round") if "retry" in event.payload)
    assert batches.batch.state is BatchState.PARTIAL_FAILED
    assert retry_event.payload["retry"] == {"state": "PARTIAL_FAILED", "tasks": [{
        "task_id": outstanding.task_id, "attempts": outstanding.attempts,
        "next_retry_at": outstanding.next_retry_at, "last_error": outstanding.last_error,
    }]}
    assert outstanding.attempts == 1
    assert outstanding.last_error == "gateway returned incomplete results"


def test_worker_uses_policy_retry_backoff_for_transient_failures() -> None:
    class UnavailableGateway:
        def run_backtests(self, _tasks):
            raise ConnectionError("temporarily unavailable")

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    policy = ResearchPolicy(
        "GBR", "TOP700", 1, max_retry_attempts=2, retry_backoff_seconds=(17, 34),
    )
    ResearchCycleUseCase(rounds, UnavailableGateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "policy-retry-round", 9, policy, KnowledgeSnapshot(version=0),
            [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )

    before = datetime.now(UTC)
    summary = ResearchBatchWorker(events, rounds, batches, knowledge, UnavailableGateway()).process_round("policy-retry-round")

    task = next(iter(batches.batch.tasks.values()))
    retry_at = datetime.fromisoformat(task.next_retry_at)
    assert summary.status == "RETRY_SCHEDULED"
    assert 16.9 <= (retry_at - before).total_seconds() <= 17.1


def test_worker_uses_retry_after_guidance_over_policy_backoff() -> None:
    class RateLimitedError(TimeoutError):
        retry_after = 73

    class RateLimitedGateway:
        def run_backtests(self, _tasks):
            raise RateLimitedError("429 rate limited")

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    policy = ResearchPolicy("GBR", "TOP700", 1, retry_backoff_seconds=(17,))
    ResearchCycleUseCase(rounds, RateLimitedGateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "retry-after-round", 9, policy, KnowledgeSnapshot(version=0),
            [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )

    before = datetime.now(UTC)
    summary = ResearchBatchWorker(events, rounds, batches, knowledge, RateLimitedGateway()).process_round("retry-after-round")

    task = next(iter(batches.batch.tasks.values()))
    retry_at = datetime.fromisoformat(task.next_retry_at)
    assert summary.status == "RETRY_SCHEDULED"
    assert 72.9 <= (retry_at - before).total_seconds() <= 73.1


def test_worker_parses_retry_after_http_date() -> None:
    class RateLimitedError(TimeoutError):
        headers = {"Retry-After": format_datetime(datetime.now(UTC) + timedelta(seconds=90), usegmt=True)}

    delay = ResearchBatchWorker._retry_after_seconds(RateLimitedError("429 rate limited"))

    assert delay is not None
    assert 88 <= delay <= 90


def test_worker_evaluates_a_rebuilt_completed_batch_without_resubmitting() -> None:
    class Gateway:
        def run_backtests(self, _tasks):
            raise AssertionError("completed replay must not resubmit platform work")

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    candidate = Candidate("c", "rank(close)", "family", ("close",), ("rank",), "template")
    policy = ResearchPolicy("GBR", "TOP700", 1)
    rounds.round = ResearchRound("completed-replay", policy, 7, [candidate])
    batch = ExperimentBatch("completed-replay", "completed-replay", BatchState.COMPLETED)
    batch.tasks["completed-replay:0"] = BacktestTask("completed-replay:0", "c", candidate.expression, {}, "completed-replay:0")
    batch.results["completed-replay:0"] = BacktestResult("completed-replay:0", candidate.expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")
    batches.batch = batch
    events.append(Event.create(EventType.POLICY_CREATED, batch.batch_id, {"policy": policy.__dict__, "seed": 7}))

    summary = ResearchBatchWorker(events, rounds, batches, knowledge, Gateway()).process_round(batch.batch_id)

    assert summary.status == "COMPLETED"
    assert batches.batch.state is BatchState.EVALUATED


def test_worker_uses_policy_retry_budget() -> None:
    class UnavailableGateway:
        def run_backtests(self, _tasks):
            raise ConnectionError("temporarily unavailable")

    events, rounds, batches, knowledge = EventStore(), RoundRepository(), BatchRepository(), KnowledgeBase()
    policy = ResearchPolicy("GBR", "TOP700", 1, max_retry_attempts=1)
    ResearchCycleUseCase(rounds, UnavailableGateway(), knowledge, batches, event_store=events).execute(
        ResearchCycleRequest(
            "retry-budget-round", 9, policy, KnowledgeSnapshot(version=0),
            [Candidate("a", "rank(close)", "family", ("close",), ("rank",), "template")], True,
        )
    )

    summary = ResearchBatchWorker(events, rounds, batches, knowledge, UnavailableGateway()).process_round("retry-budget-round")

    assert summary.status == "FAILED"
    assert batches.batch.state is BatchState.FAILED


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
