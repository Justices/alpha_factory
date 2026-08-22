"""Execution authorization tests for the DDD research cycle."""

from __future__ import annotations

import pytest

from alpha_operator_framework.ddd.application import models as application_models
from alpha_operator_framework.ddd.application.models import ResearchCycleRequest
from alpha_operator_framework.ddd.application.use_cases.orchestrator import (
    BuildSelectionFeedbackUseCase,
    DistillKnowledgeUseCase,
    GenerateCandidatesUseCase,
    OptimizeCandidatesUseCase,
    PruneAndEvaluateResultsUseCase,
    RefreshFieldUniverseUseCase,
    ResearchCycleUseCase,
    ResearchFieldsUseCase,
    RunBacktestsUseCase,
    SelectBacktestBatchUseCase,
    SubmitApprovedCandidatesUseCase,
)
from alpha_operator_framework.ddd.domain.candidate_exploration.services import CandidateFactory, PrePruningService
from alpha_operator_framework.ddd.domain.experiment_governance.services import CandidateEvaluator, ParetoOptimizer, PostBacktestPruner
from alpha_operator_framework.ddd.domain.field_research.models import FieldSnapshot
from alpha_operator_framework.ddd.domain.field_research.services import FieldEligibilityService, FieldProfiler, FieldWeightUpdater
from alpha_operator_framework.ddd.domain.knowledge_and_submission.services import SelectionFeedbackBuilder, SignalDistiller, SubmissionApprovalService
from alpha_operator_framework.ddd.infrastructure.gateways.in_memory_gateways import InMemoryBacktestGateway, InMemoryFieldCatalog, InMemorySubmissionGateway
from alpha_operator_framework.ddd.infrastructure.persistence.in_memory_repositories import (
    InMemoryCandidateRepository,
    InMemoryExperimentRepository,
    InMemoryFieldProfileRepository,
    InMemoryKnowledgeRepository,
)


def _cycle_with_spy_gateway() -> tuple[ResearchCycleUseCase, InMemoryBacktestGateway]:
    gateway = InMemoryBacktestGateway()
    catalog = InMemoryFieldCatalog([
        FieldSnapshot(field_id="field_a", dataset_id="dataset", coverage=0.95, region="GBR"),
    ])
    field_repo = InMemoryFieldProfileRepository()
    cycle = ResearchCycleUseCase(
        refresh_fields_uc=RefreshFieldUniverseUseCase(catalog, field_repo),
        research_fields_uc=ResearchFieldsUseCase(FieldProfiler(), FieldEligibilityService(), field_repo),
        generate_cands_uc=GenerateCandidatesUseCase(CandidateFactory(), InMemoryCandidateRepository()),
        select_batch_uc=SelectBacktestBatchUseCase(PrePruningService(), InMemoryCandidateRepository()),
        run_backtests_uc=RunBacktestsUseCase(gateway, InMemoryExperimentRepository()),
        prune_eval_uc=PruneAndEvaluateResultsUseCase(PostBacktestPruner(), CandidateEvaluator(), InMemoryExperimentRepository()),
        optimize_cands_uc=OptimizeCandidatesUseCase(ParetoOptimizer(), InMemoryExperimentRepository()),
        submit_uc=SubmitApprovedCandidatesUseCase(SubmissionApprovalService(), InMemorySubmissionGateway()),
        distill_uc=DistillKnowledgeUseCase(SignalDistiller(), InMemoryKnowledgeRepository()),
        feedback_uc=BuildSelectionFeedbackUseCase(SelectionFeedbackBuilder(), FieldWeightUpdater(), field_repo),
    )
    return cycle, gateway


def test_submission_authorization_requires_live_execution() -> None:
    validate = getattr(application_models, "validate_execution_flags", None)
    assert validate is not None
    with pytest.raises(ValueError, match="--authorize-submission requires --execute"):
        validate(execute_platform=False, authorize_submission=True)


def test_dry_run_stops_before_backtest_gateway() -> None:
    cycle, gateway = _cycle_with_spy_gateway()

    summary = cycle.execute(ResearchCycleRequest(execute_platform=False, seed=7))

    assert summary.status == "PLANNED"
    assert gateway.submitted_batches == []
