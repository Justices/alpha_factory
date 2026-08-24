"""Single production composition root for the event-led research lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleSummary, ResearchCycleUseCase
from alpha_operator_framework.application.research_worker import ResearchBatchWorker
from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.infrastructure.brain import build_backtest_gateway
from alpha_operator_framework.infrastructure.sqlite import (
    SqliteExperimentRepository,
    SqliteKnowledgeRepository,
    SqliteResearchRepository,
    SqliteTemplatePromotionRepository,
)
from alpha_operator_framework.infrastructure.telemetry import ResearchTelemetry


@dataclass
class ResearchRuntime:
    event_store: EventStore
    research_repository: SqliteResearchRepository
    experiment_repository: SqliteExperimentRepository
    knowledge_repository: SqliteKnowledgeRepository
    template_repository: SqliteTemplatePromotionRepository
    knowledge_base: Any
    backtest_gateway: Any
    telemetry: ResearchTelemetry
    evidence_gateway: Any | None = None
    submission_outbox: Any | None = None

    @classmethod
    def create(
        cls,
        db_path: Path,
        *,
        execute_platform: bool,
        evidence_records: Mapping[str, Mapping[str, Any]] | None = None,
        submission_authorized: bool = False,
        backtest_gateway: Any | None = None,
    ) -> "ResearchRuntime":
        knowledge_repository = SqliteKnowledgeRepository(db_path)
        evidence_gateway = submission_outbox = None
        if evidence_records is not None:
            from alpha_operator_framework.infrastructure.submission import (
                ConfiguredSubmissionEvidenceGateway,
                SqliteSubmissionOutbox,
            )
            evidence_gateway = ConfiguredSubmissionEvidenceGateway(evidence_records, submission_authorized)
            submission_outbox = SqliteSubmissionOutbox(db_path)
        return cls(
            event_store=EventStore(db_path=db_path),
            research_repository=SqliteResearchRepository(db_path),
            experiment_repository=SqliteExperimentRepository(db_path),
            knowledge_repository=knowledge_repository,
            template_repository=SqliteTemplatePromotionRepository(db_path),
            knowledge_base=knowledge_repository.load(),
            backtest_gateway=backtest_gateway or build_backtest_gateway(execute_platform=execute_platform),
            telemetry=ResearchTelemetry(),
            evidence_gateway=evidence_gateway,
            submission_outbox=submission_outbox,
        )

    def plan(self, request: ResearchCycleRequest) -> ResearchCycleSummary:
        return ResearchCycleUseCase(
            self.research_repository,
            self.backtest_gateway,
            self.knowledge_base,
            self.experiment_repository,
            self.telemetry,
            self.event_store,
            self.evidence_gateway,
            self.submission_outbox,
        ).execute(request)

    def worker(self) -> ResearchBatchWorker:
        return ResearchBatchWorker(
            self.event_store,
            self.research_repository,
            self.experiment_repository,
            self.knowledge_base,
            self.backtest_gateway,
            self.knowledge_repository,
            self.template_repository,
            self.telemetry,
            self.evidence_gateway,
            self.submission_outbox,
        )

    def process_round(self, round_id: str) -> ResearchCycleSummary:
        return self.worker().process_round(round_id)
