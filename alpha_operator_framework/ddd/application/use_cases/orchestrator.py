"""Research Cycle Application Use Cases & Full Orchestrator."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Sequence

from ...domain.ports import DeterministicRandomSource, RandomSource
from ...domain.field_research.models import FieldSnapshot, FieldUniverse
from ...domain.field_research.services import FieldEligibilityService, FieldProfiler, FieldWeightUpdater
from ...domain.field_research.ports import FieldCatalogPort, FieldProfileRepositoryPort

from ...domain.candidate_exploration.models import (
    Budget,
    Candidate,
    PrePruneDecision,
    ResearchPolicy,
    SelectionDecision,
    SelectionRound,
)
from ...domain.candidate_exploration.services import AstCanonicalizer, CandidateFactory, PrePruningService
from ...domain.candidate_exploration.policies import (
    DOptimalDiversitySelectionPolicy,
    NSGA2CandidateEvolutionPolicy,
    SelectionPolicy,
    ThompsonCombinatorialSelectionPolicy,
    UCBCombinatorialSelectionPolicy,
    WeightedStratifiedSelectionPolicy,
)
from ...domain.candidate_exploration.ports import CandidateRepositoryPort

from ...domain.experiment_governance.models import (
    BacktestTask,
    EvaluationRecord,
    ExperimentBatch,
    NormalizedBacktestResult,
    ParetoRank,
    PostPruneDecision,
)
from ...domain.experiment_governance.services import (
    CandidateEvaluator,
    ParetoOptimizer,
    PostBacktestPruner,
    ResultNormalizer,
)
from ...domain.experiment_governance.ports import BacktestGatewayPort, ExperimentRepositoryPort

from ...domain.knowledge_and_submission.models import (
    KnowledgeBase,
    PruneRuleEvidence,
    SelectionFeedback,
    SignalDistillationEvidence,
    SubmissionCase,
)
from ...domain.knowledge_and_submission.services import (
    SelectionFeedbackBuilder,
    SignalDistiller,
    SubmissionApprovalService,
)
from ...domain.knowledge_and_submission.ports import KnowledgeRepositoryPort, SubmissionGatewayPort

from ..models import ResearchCycleRequest, ResearchCycleSummary


class RefreshFieldUniverseUseCase:
    def __init__(self, catalog: FieldCatalogPort, repo: FieldProfileRepositoryPort):
        self.catalog = catalog
        self.repo = repo

    def execute(self, region: str, universe: str, dataset_ids: Optional[List[str]] = None) -> FieldUniverse:
        fu = self.repo.load_universe(region, universe) or FieldUniverse(region=region, universe=universe)
        snapshots = self.catalog.fetch_field_snapshots(region, universe, dataset_ids)
        for s in snapshots:
            fu.register_snapshot(s)
        self.repo.save_universe(fu)
        return fu


class ResearchFieldsUseCase:
    def __init__(self, profiler: FieldProfiler, eligibility: FieldEligibilityService, repo: FieldProfileRepositoryPort):
        self.profiler = profiler
        self.eligibility = eligibility
        self.repo = repo

    def execute(self, universe: FieldUniverse) -> FieldUniverse:
        self.profiler.profile_fields(universe, self.eligibility)
        self.repo.save_universe(universe)
        return universe


class GenerateCandidatesUseCase:
    def __init__(self, factory: CandidateFactory, candidate_repo: CandidateRepositoryPort):
        self.factory = factory
        self.candidate_repo = candidate_repo

    def execute(self, universe: FieldUniverse, policy: ResearchPolicy, seed: int) -> SelectionRound:
        round_id = f"round_{uuid.uuid4().hex[:8]}"
        sel_round = SelectionRound(round_id=round_id, policy=policy, seed=seed, status="INITIALIZED")

        eligible_fields = [p.field_id for p in universe.get_eligible_fields()]
        families = ["ts_momentum", "reversion", "group_neutral", "three_tier_standard", "volatility_ratio"]

        for fam in families:
            cands = self.factory.generate_family_candidates(
                fields=eligible_fields,
                family=fam,
                decay=policy.decay,
                neutralization=policy.neutralization,
            )
            for c in cands:
                sel_round.add_candidate(c)

        sel_round.status = "GENERATED"
        self.candidate_repo.save_round(sel_round)
        return sel_round


class SelectBacktestBatchUseCase:
    def __init__(self, pre_pruner: PrePruningService, candidate_repo: CandidateRepositoryPort):
        self.pre_pruner = pre_pruner
        self.candidate_repo = candidate_repo

    def execute(
        self,
        sel_round: SelectionRound,
        policy_engine: SelectionPolicy,
        random_source: RandomSource,
        context_knowledge: Any = None,
    ) -> List[Candidate]:
        # 1. Pre-prune
        seen_hashes = set()
        for cid, cand in sel_round.candidate_pool.items():
            decision = self.pre_pruner.evaluate_candidate(cand, seen_hashes, sel_round.policy)
            sel_round.record_pre_prune(decision)

        sel_round.status = "PRE_PRUNED"
        accepted_candidates = sel_round.get_accepted_pre_pruned()

        # 2. Selection algorithm
        selection_decisions = policy_engine.select(
            candidates=accepted_candidates,
            policy=sel_round.policy,
            random_source=random_source,
            context_knowledge=context_knowledge,
        )

        for d in selection_decisions:
            sel_round.record_selection(d)

        sel_round.status = "SELECTED"
        self.candidate_repo.save_round(sel_round)
        return sel_round.get_selected_cohort()


class RunBacktestsUseCase:
    def __init__(self, gateway: BacktestGatewayPort, exp_repo: ExperimentRepositoryPort):
        self.gateway = gateway
        self.exp_repo = exp_repo

    def execute(
        self,
        cohort: List[Candidate],
        policy: ResearchPolicy,
        batch_id: str,
    ) -> ExperimentBatch:
        batch = ExperimentBatch(batch_id=batch_id, idempotency_key=f"idemp_{batch_id}")
        tasks: List[BacktestTask] = []

        for idx, c in enumerate(cohort):
            t_id = f"task_{batch_id}_{idx:03d}"
            settings = {
                "region": policy.region,
                "universe": policy.universe,
                "delay": policy.delay,
                "decay": c.decay,
                "neutralization": policy.neutralization,
                "truncation": policy.truncation,
            }
            task = BacktestTask(
                task_id=t_id,
                candidate_id=c.candidate_id,
                expression=c.expression,
                decay=c.decay,
                settings=settings,
                idempotency_key=f"key_{t_id}",
            )
            batch.add_task(task)
            tasks.append(task)

        # Submit and poll via gateway
        results = self.gateway.submit_and_poll_batch(tasks, settings, batch.idempotency_key)
        for r in results:
            batch.record_result(r)

        batch.status = "COMPLETED"
        self.exp_repo.save_batch(batch)
        return batch


class PruneAndEvaluateResultsUseCase:
    def __init__(
        self,
        pruner: PostBacktestPruner,
        evaluator: CandidateEvaluator,
        exp_repo: ExperimentRepositoryPort,
    ):
        self.pruner = pruner
        self.evaluator = evaluator
        self.exp_repo = exp_repo

    def execute(self, batch: ExperimentBatch) -> ExperimentBatch:
        # 1. Post-backtest pruning
        prune_decisions = self.pruner.evaluate_batch(batch)
        for pd in prune_decisions:
            batch.record_post_prune(pd)

        # 2. 6D Evidence Gate evaluation
        for t_id, res in batch.results.items():
            eval_record = self.evaluator.evaluate(res)
            batch.record_evaluation(eval_record)

        batch.status = "EVALUATED"
        self.exp_repo.save_batch(batch)
        return batch


class OptimizeCandidatesUseCase:
    def __init__(self, pareto_opt: ParetoOptimizer, exp_repo: ExperimentRepositoryPort):
        self.pareto_opt = pareto_opt
        self.exp_repo = exp_repo

    def execute(self, batch: ExperimentBatch) -> List[ParetoRank]:
        ranked = self.pareto_opt.rank_frontier(list(batch.results.values()))
        for pr in ranked:
            batch.pareto_ranks[pr.task_id] = pr
        self.exp_repo.save_batch(batch)
        return ranked


class SubmitApprovedCandidatesUseCase:
    def __init__(
        self,
        approval_service: SubmissionApprovalService,
        gateway: SubmissionGatewayPort,
    ):
        self.approval_service = approval_service
        self.gateway = gateway

    def execute(
        self,
        batch: ExperimentBatch,
        authorize_submission: bool = False,
    ) -> List[SubmissionCase]:
        cases: List[SubmissionCase] = []
        if not authorize_submission:
            return cases

        ready_results = batch.get_ready_candidates()
        for r in ready_results:
            case_id = f"sub_{uuid.uuid4().hex[:8]}"
            sub_case = SubmissionCase(
                case_id=case_id,
                candidate_id=r.task_id,
                alpha_id=r.alpha_id,
                expression=r.expression,
            )

            # Fail-closed approval
            approval = self.approval_service.validate_for_submission(r)
            sub_case.approve(approval)

            if sub_case.status == "APPROVED":
                platform_id = self.gateway.submit_approved_case(sub_case)
                sub_case.record_submission(platform_id)

            cases.append(sub_case)

        return cases


class DistillKnowledgeUseCase:
    def __init__(self, distiller: SignalDistiller, repo: KnowledgeRepositoryPort):
        self.distiller = distiller
        self.repo = repo

    def execute(self, batch: ExperimentBatch) -> List[SignalDistillationEvidence]:
        kb = self.repo.load_knowledge() or KnowledgeBase()
        winners = [
            r for r in batch.results.values()
            if r.sharpe >= 1.0 and r.fitness >= 0.8
        ]
        evidences = self.distiller.distill_winners(winners, kb)
        self.repo.save_knowledge(kb)
        return evidences


class BuildSelectionFeedbackUseCase:
    def __init__(
        self,
        feedback_builder: SelectionFeedbackBuilder,
        weight_updater: FieldWeightUpdater,
        field_repo: FieldProfileRepositoryPort,
    ):
        self.feedback_builder = feedback_builder
        self.weight_updater = weight_updater
        self.field_repo = field_repo

    def execute(
        self,
        batch: ExperimentBatch,
        distilled: List[SignalDistillationEvidence],
        universe: FieldUniverse,
    ) -> SelectionFeedback:
        feedback = self.feedback_builder.build_feedback(
            results=list(batch.results.values()),
            distilled_templates=distilled,
            post_prunes=list(batch.post_prune_decisions.values()),
        )

        # Apply field weight feedback
        perf_map = {}
        for fid, delta in feedback.field_weight_deltas.items():
            perf_map[fid] = {
                "test_count": 1,
                "avg_sharpe": 1.0 if delta > 0 else 0.0,
                "is_alpha": delta > 0,
                "is_noise": delta < 0,
            }
        self.weight_updater.apply_feedback(universe, perf_map)
        self.field_repo.save_universe(universe)
        return feedback


# =============================================================
# Full Research Cycle Master Orchestrator Use Case
# =============================================================
class ResearchCycleUseCase:
    """Master Orchestrator executing the complete 10-stage DDD research lifecycle."""

    def __init__(
        self,
        refresh_fields_uc: RefreshFieldUniverseUseCase,
        research_fields_uc: ResearchFieldsUseCase,
        generate_cands_uc: GenerateCandidatesUseCase,
        select_batch_uc: SelectBacktestBatchUseCase,
        run_backtests_uc: RunBacktestsUseCase,
        prune_eval_uc: PruneAndEvaluateResultsUseCase,
        optimize_cands_uc: OptimizeCandidatesUseCase,
        submit_uc: SubmitApprovedCandidatesUseCase,
        distill_uc: DistillKnowledgeUseCase,
        feedback_uc: BuildSelectionFeedbackUseCase,
        random_source: Optional[RandomSource] = None,
    ):
        self.refresh_fields_uc = refresh_fields_uc
        self.research_fields_uc = research_fields_uc
        self.generate_cands_uc = generate_cands_uc
        self.select_batch_uc = select_batch_uc
        self.run_backtests_uc = run_backtests_uc
        self.prune_eval_uc = prune_eval_uc
        self.optimize_cands_uc = optimize_cands_uc
        self.submit_uc = submit_uc
        self.distill_uc = distill_uc
        self.feedback_uc = feedback_uc
        self.random_source = random_source or DeterministicRandomSource(42)

    def execute(self, req: ResearchCycleRequest) -> ResearchCycleSummary:
        rng = DeterministicRandomSource(req.seed)

        # Select policy implementation
        if req.selection_algorithm == "d_optimal":
            policy_engine: SelectionPolicy = DOptimalDiversitySelectionPolicy()
        elif req.selection_algorithm == "thompson":
            policy_engine = ThompsonCombinatorialSelectionPolicy()
        elif req.selection_algorithm == "ucb":
            policy_engine = UCBCombinatorialSelectionPolicy()
        elif req.selection_algorithm == "nsga2":
            policy_engine = NSGA2CandidateEvolutionPolicy()
        else:
            policy_engine = WeightedStratifiedSelectionPolicy()

        policy = ResearchPolicy(
            region=req.region,
            universe=req.universe,
            decay=req.decay,
            neutralization=req.neutralization,
            budget=Budget(max_backtested=req.sample_per_family * 5),
            selection_algorithm=req.selection_algorithm,
        )

        # Stage 1 & 2: Field Research
        fu = self.refresh_fields_uc.execute(req.region, req.universe, req.dataset_ids)
        fu = self.research_fields_uc.execute(fu)

        # Stage 3: Candidate Exploration
        sel_round = self.generate_cands_uc.execute(fu, policy, req.seed)

        # Stage 4: Selection with Pre-Prune
        cohort = self.select_batch_uc.execute(sel_round, policy_engine, rng)

        # Dry runs intentionally stop at the planned backtest cohort.  This
        # guard lives in the application use case so every caller, not only
        # the CLI adapter, is protected from accidental platform usage.
        if not req.execute_platform:
            pre_prune_rejections = sum(
                1 for d in sel_round.pre_prune_decisions.values() if d.is_rejected
            )
            return ResearchCycleSummary(
                round_id=sel_round.round_id,
                region=req.region,
                universe=req.universe,
                selection_algorithm=req.selection_algorithm,
                status="PLANNED",
                total_fields=len(fu.snapshots),
                eligible_fields=len(fu.get_eligible_fields()),
                candidates_generated=len(sel_round.candidate_pool),
                pre_pruned_rejected=pre_prune_rejections,
                candidates_selected=len(cohort),
            )

        # Stage 5: Run Backtests
        batch_id = f"batch_{sel_round.round_id}"
        batch = self.run_backtests_uc.execute(cohort, policy, batch_id)

        # Stage 6: Post-Prune & 6D Evaluation
        batch = self.prune_eval_uc.execute(batch)

        # Stage 7: Pareto Optimization
        self.optimize_cands_uc.execute(batch)

        # Stage 8: Submission (Opt-in)
        sub_cases = self.submit_uc.execute(batch, req.authorize_submission)

        # Stage 9: Knowledge Distillation
        distilled = self.distill_uc.execute(batch)

        # Stage 10: Feedback Loop
        feedback = self.feedback_uc.execute(batch, distilled, fu)

        # Build Summary
        pre_prune_rejections = sum(1 for d in sel_round.pre_prune_decisions.values() if d.is_rejected)
        post_pruned = sum(1 for pd in batch.post_prune_decisions.values() if pd.is_pruned)
        ready_count = sum(1 for ev in batch.evaluations.values() if ev.verdict == "READY")
        promising_count = sum(1 for ev in batch.evaluations.values() if ev.verdict == "PROMISING")

        return ResearchCycleSummary(
            round_id=sel_round.round_id,
            region=req.region,
            universe=req.universe,
            selection_algorithm=req.selection_algorithm,
            status="COMPLETED",
            total_fields=len(fu.snapshots),
            eligible_fields=len(fu.get_eligible_fields()),
            candidates_generated=len(sel_round.candidate_pool),
            pre_pruned_rejected=pre_prune_rejections,
            candidates_selected=len(cohort),
            backtests_completed=len(batch.results),
            post_pruned_count=post_pruned,
            ready_alphas_count=ready_count,
            promising_alphas_count=promising_count,
            submitted_alphas_count=len(sub_cases),
            distilled_templates_count=len(distilled),
        )
