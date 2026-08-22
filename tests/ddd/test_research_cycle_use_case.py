"""End-to-End Application Test for 10-Stage ResearchCycleUseCase."""

import pytest
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
from alpha_operator_framework.ddd.domain.experiment_governance.services import (
    CandidateEvaluator,
    ParetoOptimizer,
    PostBacktestPruner,
)
from alpha_operator_framework.ddd.domain.field_research.models import FieldSnapshot
from alpha_operator_framework.ddd.domain.field_research.services import (
    FieldEligibilityService,
    FieldProfiler,
    FieldWeightUpdater,
)
from alpha_operator_framework.ddd.domain.knowledge_and_submission.services import (
    SelectionFeedbackBuilder,
    SignalDistiller,
    SubmissionApprovalService,
)
from alpha_operator_framework.ddd.infrastructure.gateways.in_memory_gateways import (
    InMemoryBacktestGateway,
    InMemoryFieldCatalog,
    InMemorySubmissionGateway,
)
from alpha_operator_framework.ddd.infrastructure.persistence.in_memory_repositories import (
    InMemoryCandidateRepository,
    InMemoryExperimentRepository,
    InMemoryFieldProfileRepository,
    InMemoryKnowledgeRepository,
)


@pytest.fixture
def research_cycle_use_case():
    # Setup test doubles
    fields = [
        FieldSnapshot(field_id=f"feat_{i:02d}", dataset_id="ds_test", coverage=0.95, user_count=5, region="GBR")
        for i in range(10)
    ]
    catalog = InMemoryFieldCatalog(fields)
    field_repo = InMemoryFieldProfileRepository()
    cand_repo = InMemoryCandidateRepository()
    exp_repo = InMemoryExperimentRepository()
    know_repo = InMemoryKnowledgeRepository()

    backtest_gw = InMemoryBacktestGateway()
    sub_gw = InMemorySubmissionGateway()

    # Domain services
    eligibility = FieldEligibilityService(min_coverage=0.70)
    profiler = FieldProfiler()
    weight_updater = FieldWeightUpdater()
    factory = CandidateFactory()
    pre_pruner = PrePruningService(prohibited_patterns=["ts_delta(ts_delta("])
    post_pruner = PostBacktestPruner()
    evaluator = CandidateEvaluator()
    pareto_opt = ParetoOptimizer()
    approval = SubmissionApprovalService()
    distiller = SignalDistiller()
    feedback_builder = SelectionFeedbackBuilder()

    # Application use cases
    return ResearchCycleUseCase(
        refresh_fields_uc=RefreshFieldUniverseUseCase(catalog, field_repo),
        research_fields_uc=ResearchFieldsUseCase(profiler, eligibility, field_repo),
        generate_cands_uc=GenerateCandidatesUseCase(factory, cand_repo),
        select_batch_uc=SelectBacktestBatchUseCase(pre_pruner, cand_repo),
        run_backtests_uc=RunBacktestsUseCase(backtest_gw, exp_repo),
        prune_eval_uc=PruneAndEvaluateResultsUseCase(post_pruner, evaluator, exp_repo),
        optimize_cands_uc=OptimizeCandidatesUseCase(pareto_opt, exp_repo),
        submit_uc=SubmitApprovedCandidatesUseCase(approval, sub_gw),
        distill_uc=DistillKnowledgeUseCase(distiller, know_repo),
        feedback_uc=BuildSelectionFeedbackUseCase(feedback_builder, weight_updater, field_repo),
    )


def test_full_research_cycle_dry_run(research_cycle_use_case):
    req = ResearchCycleRequest(
        region="GBR",
        universe="TOP700",
        selection_algorithm="stratified",
        sample_per_family=2,
        execute_platform=False,
        authorize_submission=False,
        seed=42,
    )

    summary = research_cycle_use_case.execute(req)

    assert summary.status == "COMPLETED"
    assert summary.total_fields == 10
    assert summary.eligible_fields == 10
    assert summary.candidates_generated >= 50
    assert summary.candidates_selected >= 8
    assert summary.backtests_completed >= 8
    assert summary.ready_alphas_count >= 1
    assert summary.submitted_alphas_count == 0  # Dry-run: no platform submission
    assert summary.distilled_templates_count >= 1

    cli_text = summary.format_cli_report()
    assert "Alpha Factory DDD Research Cycle Summary" in cli_text


def test_full_research_cycle_with_authorized_submission(research_cycle_use_case):
    req = ResearchCycleRequest(
        region="GBR",
        universe="TOP700",
        selection_algorithm="d_optimal",
        sample_per_family=2,
        execute_platform=True,
        authorize_submission=True,  # Explicit opt-in
        seed=100,
    )

    summary = research_cycle_use_case.execute(req)

    assert summary.status == "COMPLETED"
    assert summary.selection_algorithm == "d_optimal"
    assert summary.submitted_alphas_count >= 1  # Successfully submitted approved cases
