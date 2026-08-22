"""In-Memory Test Repositories for All Bounded Contexts."""

from __future__ import annotations

from typing import Dict, Optional
from ...domain.field_research.models import FieldUniverse
from ...domain.field_research.ports import FieldProfileRepositoryPort
from ...domain.candidate_exploration.models import SelectionRound
from ...domain.candidate_exploration.ports import CandidateRepositoryPort
from ...domain.experiment_governance.models import ExperimentBatch
from ...domain.experiment_governance.ports import ExperimentRepositoryPort
from ...domain.knowledge_and_submission.models import KnowledgeBase
from ...domain.knowledge_and_submission.ports import KnowledgeRepositoryPort


class InMemoryFieldProfileRepository(FieldProfileRepositoryPort):
    def __init__(self):
        self.universes: Dict[tuple[str, str], FieldUniverse] = {}

    def load_universe(self, region: str, universe: str) -> Optional[FieldUniverse]:
        return self.universes.get((region, universe))

    def save_universe(self, universe: FieldUniverse) -> None:
        self.universes[(universe.region, universe.universe)] = universe


class InMemoryCandidateRepository(CandidateRepositoryPort):
    def __init__(self):
        self.rounds: Dict[str, SelectionRound] = {}

    def save_round(self, selection_round: SelectionRound) -> None:
        self.rounds[selection_round.round_id] = selection_round

    def load_round(self, round_id: str) -> Optional[SelectionRound]:
        return self.rounds.get(round_id)


class InMemoryExperimentRepository(ExperimentRepositoryPort):
    def __init__(self):
        self.batches: Dict[str, ExperimentBatch] = {}

    def save_batch(self, batch: ExperimentBatch) -> None:
        self.batches[batch.batch_id] = batch

    def load_batch(self, batch_id: str) -> Optional[ExperimentBatch]:
        return self.batches.get(batch_id)


class InMemoryKnowledgeRepository(KnowledgeRepositoryPort):
    def __init__(self):
        self.kb = KnowledgeBase()

    def load_knowledge(self) -> KnowledgeBase:
        return self.kb

    def save_knowledge(self, knowledge_base: KnowledgeBase) -> None:
        self.kb = knowledge_base
