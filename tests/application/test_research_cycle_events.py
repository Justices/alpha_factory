"""Event-store integration for the new research cycle."""

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleUseCase
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import EventType
from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.knowledge.submission import SubmissionEvidence
from alpha_operator_framework.infrastructure.brain import DryRunGateway
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy


class Repository:
    def save_round(self, round_): pass


class BatchRepository:
    def __init__(self): self.batch = None
    def load_batch(self, _): return self.batch
    def save_batch(self, batch): self.batch = batch


def test_dry_run_appends_replayable_research_events() -> None:
    events = EventStore()
    use_case = ResearchCycleUseCase(Repository(), DryRunGateway(), KnowledgeBase(), event_store=events)
    request = ResearchCycleRequest("event-round", 7, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
                                   [Candidate("c", "rank(returns)", "family", ("returns",), ("rank",), "template")],
                                   catalog_round_id="event-round")

    use_case.execute(request)

    assert [event.event_type for event in events.read_stream("event-round")] == [
        EventType.POLICY_CREATED, EventType.FIELD_SNAPSHOT_CAPTURED, EventType.CANDIDATE_GENERATED,
        EventType.CANDIDATE_SCORED, EventType.BATCH_ALLOCATED,
    ]


def test_live_cycle_appends_only_simulation_request_events() -> None:
    class Gateway:
        def run_backtests(self, tasks):
            return [BacktestResult(tasks[0].task_id, tasks[0].expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")]
    events = EventStore()
    use_case = ResearchCycleUseCase(Repository(), Gateway(), KnowledgeBase(), BatchRepository(), event_store=events)
    request = ResearchCycleRequest("live-event-round", 7, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
                                   [Candidate("c", "rank(returns)", "family", ("returns",), ("rank",), "template")], True,
                                   catalog_round_id="live-event-round")

    use_case.execute(request)

    kinds = [event.event_type for event in events.read_stream("live-event-round")]
    assert EventType.SIMULATION_REQUESTED in kinds
    assert EventType.SIMULATION_COMPLETED not in kinds


def test_live_cycle_defers_approval_until_worker_execution() -> None:
    class Gateway:
        def run_backtests(self, tasks): return [BacktestResult(tasks[0].task_id, tasks[0].expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")]
    class EvidenceGateway:
        def evidence_for(self, result): return SubmissionEvidence(True, True, True, True, True)
    events = EventStore()
    use_case = ResearchCycleUseCase(Repository(), Gateway(), KnowledgeBase(), BatchRepository(), event_store=events, evidence_gateway=EvidenceGateway())
    request = ResearchCycleRequest("approved-event-round", 7, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
                                   [Candidate("c", "rank(returns)", "family", ("returns",), ("rank",), "template")], True,
                                   catalog_round_id="approved-event-round")

    use_case.execute(request)

    assert EventType.DECISION_APPROVED not in [event.event_type for event in events.read_stream("approved-event-round")]


def test_planner_never_enqueues_submission_without_worker_execution() -> None:
    class Gateway:
        def run_backtests(self, tasks): return [BacktestResult(tasks[0].task_id, tasks[0].expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")]
    class EvidenceGateway:
        def evidence_for(self, result): return SubmissionEvidence(True, True, True, True, True)
    class Outbox:
        def __init__(self): self.cases = []
        def enqueue(self, case): self.cases.append(case)
    outbox = Outbox()
    use_case = ResearchCycleUseCase(Repository(), Gateway(), KnowledgeBase(), BatchRepository(), event_store=EventStore(), evidence_gateway=EvidenceGateway(), submission_outbox=outbox)
    request = ResearchCycleRequest("outbox-round", 7, ResearchPolicy("GBR", "TOP700", 1), KnowledgeSnapshot(version=0),
                                   [Candidate("c", "rank(returns)", "family", ("returns",), ("rank",), "template")], True,
                                   catalog_round_id="outbox-round")

    use_case.execute(request)

    assert outbox.cases == []
