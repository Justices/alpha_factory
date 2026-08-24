from alpha_operator_framework.application.research_rebuild import ResearchProjectionRebuilder
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
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
