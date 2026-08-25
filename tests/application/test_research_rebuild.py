import pytest

from alpha_operator_framework.application.research_rebuild import ResearchProjectionRebuilder
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.experiment.lifecycle import BatchState
from alpha_operator_framework.experiment.models import ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase


class Rounds:
    def save_round(self, value): self.value = value
    def load_round(self, _): return getattr(self, "value", None)


class Batches:
    def save_batch(self, value): self.value = value
    def load_batch(self, _): return getattr(self, "value", None)


class Knowledge:
    def save(self, value): self.value = value


class KnowledgeWithMetadata:
    def save(self, value, **metadata):
        self.value = value
        self.metadata = metadata


def test_rebuild_restores_round_batch_and_knowledge_idempotently() -> None:
    events, rounds, batches, knowledge = EventStore(), Rounds(), Batches(), Knowledge()
    stream = "rebuild-round"
    events.append(Event.create(EventType.POLICY_CREATED, stream, {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 1}, "seed": 7}))
    events.append(Event.create(EventType.CANDIDATE_GENERATED, stream, {"candidate": {"candidate_id": "c1", "expression": "rank(close)", "family": "f", "fields": ["close"], "operators": ["rank"], "template_id": "t", "novelty_score": 0.0, "lineage_parent_id": None}}))
    events.append(Event.create(EventType.SIMULATION_REQUESTED, stream, {"task_id": "rebuild-round:0", "candidate_id": "c1", "expression": "rank(close)", "settings": {"region": "GBR"}, "idempotency_key": "rebuild-round:0"}))
    events.append(Event.create(EventType.SIMULATION_COMPLETED, stream, {"task_id": "rebuild-round:0", "alpha_id": "a1", "sharpe": 1.5, "fitness": 1.1, "turnover": 0.2, "margin": 5.0, "checks_passed": True}))
    events.append(Event.create(EventType.VALIDATION_COMPUTED, stream, {"task_id": "rebuild-round:0", "verdict": "READY", "pareto_rank": 1, "pruned": False}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"knowledge": {"version": 1, "field_scores": {"close": 0.2}, "operator_scores": {"rank": 0.2}, "template_scores": {"t": 0.2}, "rejected_templates": [], "field_trials": {"close": 1}}}))

    rebuilder = ResearchProjectionRebuilder(events, rounds, batches, KnowledgeBase(), knowledge)
    rebuilder.rebuild(stream)
    rebuilder.rebuild(stream)

    assert rounds.value.round_id == stream
    assert isinstance(batches.value, ExperimentBatch)
    assert batches.value.results["rebuild-round:0"].platform_alpha_id == "a1"
    assert knowledge.value.version == 1


def test_rebuild_restores_retry_facts_partial_failure_and_knowledge_source_metadata() -> None:
    events, rounds, batches, knowledge = EventStore(), Rounds(), Batches(), KnowledgeWithMetadata()
    stream = "retry-rebuild-round"
    events.append(Event.create(EventType.POLICY_CREATED, stream, {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 2, "policy_version": "retry-v1"}, "seed": 7}))
    for index in range(2):
        events.append(Event.create(EventType.SIMULATION_REQUESTED, stream, {"task_id": f"{stream}:{index}", "candidate_id": f"c{index}", "expression": "rank(close)", "settings": {"region": "GBR"}, "idempotency_key": f"{stream}:{index}"}))
    events.append(Event.create(EventType.SIMULATION_COMPLETED, stream, {"task_id": f"{stream}:0", "alpha_id": "a1", "sharpe": 1.5, "fitness": 1.1, "turnover": 0.2, "margin": 5.0, "checks_passed": True}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"retry": {"state": "PARTIAL_FAILED", "tasks": [{"task_id": f"{stream}:1", "attempts": 2, "next_retry_at": "2026-08-24T01:02:03+00:00", "last_error": "429 rate limited"}]}}))
    knowledge_event_offset = events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"knowledge": {"version": 1, "field_scores": {}, "operator_scores": {}, "template_scores": {}, "rejected_templates": [], "field_trials": {}}}))

    ResearchProjectionRebuilder(events, rounds, batches, KnowledgeBase(), knowledge).rebuild(stream)

    retried = batches.value.tasks[f"{stream}:1"]
    assert batches.value.state.value == "PARTIAL_FAILED"
    assert (retried.attempts, retried.next_retry_at, retried.last_error) == (2, "2026-08-24T01:02:03+00:00", "429 rate limited")
    assert batches.value.results[f"{stream}:0"].platform_alpha_id == "a1"
    assert knowledge.metadata == {"round_id": stream, "policy_version": "retry-v1", "event_offset": knowledge_event_offset}


def test_rebuild_latest_retry_failure_overrides_an_earlier_evaluation() -> None:
    events, rounds, batches, knowledge = EventStore(), Rounds(), Batches(), Knowledge()
    stream = "failed-rebuild-round"
    events.append(Event.create(EventType.POLICY_CREATED, stream, {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 1}, "seed": 7}))
    events.append(Event.create(EventType.SIMULATION_REQUESTED, stream, {"task_id": f"{stream}:0", "candidate_id": "c0", "expression": "rank(close)", "settings": {"region": "GBR"}, "idempotency_key": f"{stream}:0"}))
    events.append(Event.create(EventType.VALIDATION_COMPUTED, stream, {"task_id": f"{stream}:0", "verdict": "READY", "pareto_rank": 1, "pruned": False}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"retry": {"state": "FAILED", "tasks": [{"task_id": f"{stream}:0", "attempts": 3, "next_retry_at": "2026-08-24T01:02:03+00:00", "last_error": "unavailable"}]}}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"knowledge": {"version": 1, "field_scores": {}, "operator_scores": {}, "template_scores": {}, "rejected_templates": [], "field_trials": {}}}))

    ResearchProjectionRebuilder(events, rounds, batches, KnowledgeBase(), knowledge).rebuild(stream)

    assert batches.value.state.value == "FAILED"


def test_rebuild_complete_results_supersede_earlier_partial_retry_state() -> None:
    events, rounds, batches, knowledge = EventStore(), Rounds(), Batches(), Knowledge()
    stream = "completed-after-retry-round"
    events.append(Event.create(EventType.POLICY_CREATED, stream, {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 2}, "seed": 7}))
    for index in range(2):
        events.append(Event.create(EventType.SIMULATION_REQUESTED, stream, {"task_id": f"{stream}:{index}", "candidate_id": f"c{index}", "expression": "rank(close)", "settings": {"region": "GBR"}, "idempotency_key": f"{stream}:{index}"}))
    events.append(Event.create(EventType.SIMULATION_COMPLETED, stream, {"task_id": f"{stream}:0", "alpha_id": "a0", "sharpe": 1.5, "fitness": 1.1, "turnover": 0.2, "margin": 5.0, "checks_passed": True}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"retry": {"state": "PARTIAL_FAILED", "tasks": [{"task_id": f"{stream}:1", "attempts": 1, "next_retry_at": "2026-08-24T01:02:03+00:00", "last_error": "partial"}]}}))
    events.append(Event.create(EventType.SIMULATION_COMPLETED, stream, {"task_id": f"{stream}:1", "alpha_id": "a1", "sharpe": 1.6, "fitness": 1.2, "turnover": 0.2, "margin": 5.0, "checks_passed": True}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"knowledge": {"version": 1, "field_scores": {}, "operator_scores": {}, "template_scores": {}, "rejected_templates": [], "field_trials": {}}}))

    ResearchProjectionRebuilder(events, rounds, batches, KnowledgeBase(), knowledge).rebuild(stream)

    assert batches.value.state is BatchState.COMPLETED


def test_rebuild_propagates_type_error_from_metadata_capable_knowledge_repository() -> None:
    class BrokenKnowledge:
        def save(self, _value, **metadata):
            if metadata:
                raise TypeError("database constraint")

    events, rounds, batches = EventStore(), Rounds(), Batches()
    stream = "broken-knowledge-round"
    events.append(Event.create(EventType.POLICY_CREATED, stream, {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 1}, "seed": 7}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"knowledge": {"version": 1, "field_scores": {}, "operator_scores": {}, "template_scores": {}, "rejected_templates": [], "field_trials": {}}}))

    with pytest.raises(TypeError, match="database constraint"):
        ResearchProjectionRebuilder(events, rounds, batches, KnowledgeBase(), BrokenKnowledge()).rebuild(stream)


def test_rebuild_uses_the_source_event_global_offset_not_its_stream_position() -> None:
    class OffsetRepository:
        def __init__(self):
            self.rows = []
            self.offsets = iter((10, 20, 40))

        def append_event(self, **values):
            offset = next(self.offsets)
            self.rows.append({
                "global_offset": offset, "event_id": values["event_id"], "stream_id": values["stream_id"],
                "event_type": values["event_type"], "schema_version": values["schema_version"],
                "payload": values["payload_json"], "payload_ref": values["payload_ref"],
                "occurred_at": values["occurred_at"], "actor": values["actor"], "metadata": values["metadata_json"],
            })
            return offset

        def read_events_by_stream(self, stream_id, _from_offset):
            return [row for row in self.rows if row["stream_id"] == stream_id]

        def read_all_events(self, _from_offset, _limit):
            return self.rows

    repository = OffsetRepository()
    events, rounds, batches, knowledge = EventStore(persistent=True, repository=repository), Rounds(), Batches(), KnowledgeWithMetadata()
    stream = "offset-round"
    events.append(Event.create(EventType.POLICY_CREATED, stream, {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 1}, "seed": 7}))
    events.append(Event.create(EventType.POLICY_CREATED, "other-round", {"policy": {"region": "GBR", "universe": "TOP700", "max_backtests": 1}, "seed": 8}))
    events.append(Event.create(EventType.MONITORING_OBSERVED, stream, {"knowledge": {"version": 1, "field_scores": {}, "operator_scores": {}, "template_scores": {}, "rejected_templates": [], "field_trials": {}}}))

    ResearchProjectionRebuilder(events, rounds, batches, KnowledgeBase(), knowledge).rebuild(stream)

    assert knowledge.metadata["event_offset"] == 40
