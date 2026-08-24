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
