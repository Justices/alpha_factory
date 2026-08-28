"""Closed-loop orchestration for explicitly configured construction strategies."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Sequence

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest
from alpha_operator_framework.research.optimization import derive_consensus_prune_rules
from alpha_operator_framework.research.round import Candidate, ResearchPolicy
from alpha_operator_framework.research.strategies import (
    ConstructionContext,
    ConstructionOutcome,
    ConstructionStrategyRegistry,
    StrategyStatus,
)
from alpha_operator_framework.research.strategy_config import ConstructionPlan


RESEARCH_SHARD_SIZE = 8
RETRY_WAIT_CAP_SECONDS = 60.0
RETRYABLE_STATUSES = frozenset({"RETRY_SCHEDULED", "PARTIAL_FAILED"})


@dataclass(frozen=True)
class ResearchLoopSummary:
    status: str
    round_ids: list[str]
    completed_backtests: int
    pruned_count: int
    generated_optimization_count: int
    strategy_statuses: tuple[StrategyStatus, ...] = ()


class ResearchLoopCoordinator:
    """Run configured construction sources and deterministic eight-candidate shards."""

    def __init__(self, runtime: Any, registry: ConstructionStrategyRegistry | None = None) -> None:
        self.runtime = runtime
        self.registry = registry or ConstructionStrategyRegistry()

    def prepare(
        self,
        task_id: str,
        policy: ResearchPolicy,
        fields: Sequence[Any],
        construction_plan: ConstructionPlan,
        *,
        seed: int,
        parents: Sequence[Candidate] = (),
    ) -> ConstructionOutcome:
        """Generate and persist the initial canonical pool before any selection."""
        database = self._database()
        if database.construction_task_exists(task_id):
            raise ValueError(f"construction task already exists; resume it explicitly: {task_id}")
        settings = self._settings(policy)
        database.save_construction_task(
            task_id, settings, construction_plan.to_mapping(), seed, "GENERATING",
        )
        context = ConstructionContext(
            fields=tuple(fields),
            templates=tuple(database.list_templates(active_only=True)),
            parents=tuple(parents),
            seed=seed,
        )
        outcome = self.registry.generate(construction_plan, context)
        self._persist_outcome(task_id, settings, construction_plan, outcome)
        status = "PARTIAL_FAILED" if outcome.partial_failed else "GENERATED"
        errors = "; ".join(item.error for item in outcome.strategy_statuses if item.error)
        database.save_construction_task(
            task_id, settings, construction_plan.to_mapping(), seed, status, errors,
        )
        return outcome

    def run(
        self,
        policy: ResearchPolicy,
        fields: Sequence[Any],
        base_candidates: Sequence[Candidate],
        *,
        construction_plan: ConstructionPlan,
        seed: int,
        execute: bool,
        base_round_id: str = "research-loop",
        strategy_statuses: Sequence[StrategyStatus] = (),
    ) -> ResearchLoopSummary:
        if not execute:
            raise ValueError("continuous research requires platform execution")
        database = self._database()
        settings = self._settings(policy)
        round_ids: list[str] = []
        completed_backtests = pruned_count = generated_count = 0
        statuses = list(strategy_statuses)
        partial_failed = any(status.status == "FAILED" for status in statuses)
        initial_candidates = list(base_candidates)
        initial_available = True
        round_sequence = database.next_task_round_sequence(base_round_id)

        while True:
            pending = database.load_unbacktested_research_candidates(settings)
            candidates = pending
            if not candidates and initial_available:
                candidates = initial_candidates
            initial_available = False
            selected_counts = database.selected_counts_by_family(base_round_id)
            shard = self._next_shard(candidates, construction_plan, selected_counts)
            if not shard:
                final_status = "PARTIAL_FAILED" if partial_failed else "EXHAUSTED"
                database.save_construction_task(
                    base_round_id,
                    settings,
                    construction_plan.to_mapping(),
                    seed,
                    final_status,
                    "; ".join(status.error for status in statuses if status.error),
                )
                return ResearchLoopSummary(
                    final_status, round_ids, completed_backtests, pruned_count,
                    generated_count, tuple(statuses),
                )

            round_policy = self._policy_for_candidates(policy, shard)
            round_id = base_round_id if round_sequence == 1 else f"{base_round_id}-{round_sequence}"
            planned = self.runtime.plan(ResearchCycleRequest(
                round_id,
                seed,
                round_policy,
                self.runtime.knowledge_base.snapshot(),
                shard,
                True,
            ))
            round_ids.append(planned.round_id)
            round_sequence += 1
            summary = self._process_until_terminal(planned.round_id)
            if summary.status != "COMPLETED":
                return ResearchLoopSummary(
                    summary.status, round_ids, completed_backtests, pruned_count,
                    generated_count, tuple(statuses),
                )
            completed_backtests += summary.completed_backtests

            rows = database.load_completed_expression_results(settings)
            for rule in derive_consensus_prune_rules(rows):
                database.upsert_result_prune_rule(settings, rule.pattern, rule.pattern_type, rule.reason)
            pruned_count += len(database.prune_unbacktested_matching(
                settings, database.get_result_prune_rules(settings),
            ))
            generated, parent_statuses = self._generate_from_qualified_parents(
                base_round_id, database, settings, fields, rows, construction_plan, seed,
            )
            generated_count += generated
            statuses.extend(parent_statuses)
            partial_failed = partial_failed or any(
                status.status == "FAILED" for status in parent_statuses
            )

    def _database(self) -> Any:
        database = self.runtime.alpha_database
        if database is None:
            raise ValueError("continuous research requires an alpha database")
        return database

    @staticmethod
    def _settings(policy: ResearchPolicy) -> dict[str, object]:
        return {
            "region": policy.region,
            "universe": policy.universe,
            "delay": policy.delay,
            "decay": policy.decay,
            "neutralization": policy.neutralization,
            "truncation": policy.truncation,
        }

    @staticmethod
    def _next_shard(
        candidates: Sequence[Candidate],
        plan: ConstructionPlan,
        selected_counts: dict[str, int],
    ) -> list[Candidate]:
        if not candidates:
            return []
        configs = {config.strategy_id: config for config in plan.strategies}
        by_family: dict[str, list[Candidate]] = defaultdict(list)
        remaining: dict[str, int] = {}
        for candidate in sorted(candidates, key=lambda item: (item.family, item.candidate_id)):
            config = configs.get(candidate.origin_strategy)
            if config is None:
                config = next(
                    (item for item in plan.strategies if candidate.family.startswith(f"{item.kind}/")),
                    None,
                )
            quota = config.quota_per_leaf_family if config is not None else 0
            available = max(0, quota - int(selected_counts.get(candidate.family, 0)))
            if available:
                by_family[candidate.family].append(candidate)
                remaining[candidate.family] = available
        shard: list[Candidate] = []
        families = sorted(by_family)
        while families and len(shard) < RESEARCH_SHARD_SIZE:
            next_families: list[str] = []
            for family in families:
                if len(shard) >= RESEARCH_SHARD_SIZE:
                    break
                pool = by_family[family]
                if pool and remaining[family] > 0:
                    shard.append(pool.pop(0))
                    remaining[family] -= 1
                if pool and remaining[family] > 0:
                    next_families.append(family)
            families = next_families
        return shard

    @staticmethod
    def _policy_for_candidates(
        policy: ResearchPolicy,
        candidates: Sequence[Candidate],
    ) -> ResearchPolicy:
        quotas = dict(Counter(candidate.family for candidate in candidates))
        return replace(policy, max_backtests=len(candidates), family_quotas=quotas)

    def _generate_from_qualified_parents(
        self,
        task_id: str,
        database: Any,
        settings: dict[str, object],
        fields: Sequence[Any],
        rows: Sequence[Any],
        plan: ConstructionPlan,
        seed: int,
    ) -> tuple[int, list[StrategyStatus]]:
        templates = tuple(database.list_templates(active_only=True))
        generated = 0
        statuses: list[StrategyStatus] = []
        priorities = {config.strategy_id: index for index, config in enumerate(plan.strategies)}
        for row in rows:
            if not row.checks_passed or not plan.parent_gate.passes(row.sharpe, row.fitness):
                continue
            parent = Candidate(
                candidate_id=row.alpha_sha or row.expression,
                expression=row.expression,
                family=row.family,
                fields=tuple(row.fields),
                operators=(),
                template_id="qualified-parent",
            )
            for config in plan.strategies:
                if not config.consumes_parents:
                    continue
                if database.has_parent_strategy_run(settings, parent.candidate_id, config.strategy_id):
                    continue
                parent_config = replace(config, source="qualified_candidates")
                parent_plan = ConstructionPlan((parent_config,), plan.parent_gate, plan.platform_batch_size)
                context = ConstructionContext(tuple(fields), templates, (parent,), seed)
                outcome = self.registry.generate(parent_plan, context)
                priority = priorities[config.strategy_id]
                outcome.provenances = [
                    replace(item, strategy_priority=priority) for item in outcome.provenances
                ]
                self._persist_outcome(task_id, settings, plan, outcome)
                status = outcome.strategy_statuses[0]
                statuses.append(status)
                database.record_parent_strategy_run(
                    settings,
                    parent.candidate_id,
                    config.strategy_id,
                    status.status,
                    len(outcome.candidates),
                    status.error,
                )
                child_by_id = {candidate.candidate_id: candidate for candidate in outcome.candidates}
                for provenance in outcome.provenances:
                    child = child_by_id.get(provenance.candidate_id)
                    if child is None:
                        continue
                    child_sha = database.compute_alpha_sha(child.expression, settings)
                    for parent_sha in provenance.parent_ids:
                        database.record_construction_lineage(
                            settings, parent_sha, child_sha, config.kind, config.strategy_id,
                        )
                generated += len(outcome.candidates)
        return generated, statuses

    def _persist_outcome(
        self,
        task_id: str,
        settings: dict[str, object],
        plan: ConstructionPlan,
        outcome: ConstructionOutcome,
    ) -> None:
        database = self._database()
        priorities = {config.strategy_id: index for index, config in enumerate(plan.strategies)}
        for status in outcome.strategy_statuses:
            database.save_strategy_outcome(
                task_id,
                status.strategy_id,
                status.kind,
                priorities.get(status.strategy_id, 0),
                status.status,
                status.generated_count,
                status.error,
            )
        candidate_by_id = {candidate.candidate_id: candidate for candidate in outcome.candidates}
        for candidate in outcome.candidates:
            database.insert_expression(
                candidate.expression,
                settings,
                expression_origin=candidate.origin_strategy,
                fields=list(candidate.fields),
                status="generated",
            )
        for provenance in outcome.provenances:
            candidate = candidate_by_id.get(provenance.candidate_id)
            if candidate is None:
                continue
            candidate_sha = database.compute_alpha_sha(candidate.expression, settings)
            database.record_candidate_provenance(settings, candidate_sha, provenance)
        if outcome.candidates:
            database.catalog_research_candidates(f"{task_id}-catalog", outcome.candidates, settings)

    def _process_until_terminal(self, round_id: str) -> Any:
        while True:
            summary = self.runtime.process_round(round_id)
            if summary.status not in RETRYABLE_STATUSES:
                return summary
            self._wait_for_retry(round_id)

    def _wait_for_retry(self, round_id: str) -> None:
        batch = self.runtime.experiment_repository.load_batch(round_id)
        retry_times = [
            datetime.fromisoformat(task.next_retry_at)
            for task in batch.tasks.values()
            if task.task_id not in batch.results and task.next_retry_at
        ] if batch is not None else []
        if not retry_times:
            time.sleep(1.0)
            return
        now = datetime.now(UTC)
        delay = max(0.0, min((retry_at - now).total_seconds() for retry_at in retry_times))
        time.sleep(min(delay, RETRY_WAIT_CAP_SECONDS))
