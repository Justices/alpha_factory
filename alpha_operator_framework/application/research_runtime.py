"""Single production composition root for the event-led research lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleSummary, ResearchCycleUseCase
from alpha_operator_framework.application.research_worker import ResearchBatchWorker


@dataclass
class ResearchRuntime:
    event_store: Any
    research_repository: Any
    experiment_repository: Any
    knowledge_repository: Any
    template_repository: Any
    knowledge_base: Any
    backtest_gateway: Any
    telemetry: Any
    evidence_gateway: Any | None = None
    submission_outbox: Any | None = None
    alpha_database: Any | None = None
    engine: Any | None = None

    def close(self) -> None:
        """Release the primary repository connection and shared SQLAlchemy engine."""
        try:
            if self.alpha_database is not None:
                self.alpha_database.close()
        finally:
            if self.engine is not None:
                self.engine.dispose()

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
            self.alpha_database,
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
            self.alpha_database,
        )

    def process_round(self, round_id: str) -> ResearchCycleSummary:
        if self.research_repository.load_round(round_id) is None:
            from alpha_operator_framework.application.research_rebuild import ResearchProjectionRebuilder

            ResearchProjectionRebuilder(
                self.event_store, self.research_repository, self.experiment_repository,
                self.knowledge_base, self.knowledge_repository,
            ).rebuild(round_id)
        return self.worker().process_round(round_id)
