"""Closed-loop orchestration for explicitly configured construction strategies."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Sequence

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest
from alpha_operator_framework.domain.pruning_components import (
    MultiChannelCorrelationConfig,
    multi_channel_correlation_prune,
)
from alpha_operator_framework.research.optimization import (
    derive_consensus_prune_rules,
    is_signal_parent,
    promotion_quality_reason,
)
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
            region=policy.region,
            universe=policy.universe,
            delay=policy.delay,
        )
        initial_plan = ConstructionPlan(
            construction_plan.strategies_for_stage(1),
            construction_plan.parent_gate,
            construction_plan.platform_batch_size,
            construction_plan.promotion,
            construction_plan.rolling_capacity_queue,
            construction_plan.selection_window_batches,
        )
        outcome = self.registry.generate(initial_plan, context)
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
        catalog_round_id = f"{base_round_id}-catalog"
        cap_catalog = getattr(database, "prune_catalog_candidates_beyond_family_quota", None)
        if (not construction_plan.rolling_capacity_queue and callable(cap_catalog)
                and self._catalog_family_quotas(construction_plan)):
            pruned_count += cap_catalog(catalog_round_id, self._catalog_family_quotas(construction_plan))

        while True:
            pending = self._load_task_candidates(database, settings, catalog_round_id)
            candidates = pending
            if not candidates and initial_available:
                candidates = initial_candidates
            initial_available = False
            candidates = self._bounded_selection_window(candidates, construction_plan)
            selected_counts = database.selected_counts_by_family(base_round_id)
            selection_pool = self._next_shard(candidates, construction_plan, selected_counts)
            if not selection_pool:
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

            round_policy = self._policy_for_candidates(
                policy, selection_pool, construction_plan, selected_counts,
            )
            round_id = base_round_id if round_sequence == 1 else f"{base_round_id}-{round_sequence}"
            planned = self.runtime.plan(ResearchCycleRequest(
                round_id,
                seed,
                round_policy,
                self.runtime.knowledge_base.snapshot(),
                selection_pool,
                True,
            ))
            if planned.status == "NO_ELIGIBLE_CANDIDATES":
                # The selector has conclusively rejected this shard.  Its
                # source rows live in the task catalog (rather than this
                # ephemeral planning round), so prune them there before
                # looking for another shard.  Otherwise the same expression
                # would be planned again indefinitely.
                rejected_ids = [
                    str(item["candidate_id"])
                    for item in planned.selection_audit
                    if not bool(item["selected"])
                ]
                mark_pruned = getattr(database, "mark_round_candidates_pruned", None)
                if callable(mark_pruned):
                    mark_pruned(catalog_round_id, rejected_ids)
                pruned_count += len(rejected_ids)
                continue
            if planned.status != "SUBMITTED":
                return ResearchLoopSummary(
                    planned.status, round_ids, completed_backtests, pruned_count,
                    generated_count, tuple(statuses),
                )
            # A rolling queue retains unselected candidates for the next
            # platform-capacity window; legacy mode keeps one-off leaf quotas.
            unselected_ids = [
                str(item["candidate_id"])
                for item in planned.selection_audit
                if not bool(item["selected"])
            ]
            if not construction_plan.rolling_capacity_queue:
                mark_pruned = getattr(database, "mark_round_candidates_pruned", None)
                if callable(mark_pruned):
                    mark_pruned(catalog_round_id, unselected_ids)
                pruned_count += len(unselected_ids)
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
            self._evaluate_signal_validations(database, settings, construction_plan)
            derived_rules = derive_consensus_prune_rules(
                rows, sharpe_gate=construction_plan.parent_gate.sharpe,
            )
            replace_rules = getattr(database, "replace_result_prune_rules", None)
            if callable(replace_rules):
                replace_rules(settings, [
                    {
                        "pattern": rule.pattern,
                        "pattern_type": rule.pattern_type,
                        "reason": rule.reason,
                    }
                    for rule in derived_rules
                ])
            else:
                # Compatibility for lightweight adapters; production storage
                # replaces the complete derived set so stale thresholds expire.
                for rule in derived_rules:
                    database.upsert_result_prune_rule(
                        settings, rule.pattern, rule.pattern_type, rule.reason,
                    )
            pruned_count += len(database.prune_unbacktested_matching(
                settings, database.get_result_prune_rules(settings),
            ))
            retained_rows, promotion_rows, target_stages = self._select_promotion_rows(
                base_round_id, database, settings, rows, construction_plan,
            )
            self._queue_signal_candidates(database, retained_rows)
            generated, parent_statuses = self._generate_from_qualified_parents(
                base_round_id, database, settings, fields, promotion_rows, construction_plan, seed,
                target_stages=target_stages,
            )
            generated_count += generated
            statuses.extend(parent_statuses)
            partial_failed = partial_failed or any(
                status.status == "FAILED" for status in parent_statuses
            )

    @staticmethod
    def _bounded_selection_window(
        candidates: Sequence[Candidate],
        plan: ConstructionPlan,
    ) -> list[Candidate]:
        """Bound scoring/audit volume without imposing a stage backtest quota."""
        window_size = plan.platform_batch_size * plan.selection_window_batches
        return sorted(
            candidates, key=lambda item: (item.family, item.candidate_id),
        )[:window_size]

    @staticmethod
    def _catalog_family_quotas(plan: ConstructionPlan) -> dict[str, int]:
        quotas: dict[str, int] = {}
        for config in plan.strategies:
            if config.generation_pool_per_leaf is None:
                continue
            for depth in range(config.order_depth.minimum or config.order_depth.exact or 0,
                               (config.order_depth.maximum or config.order_depth.exact or 0) + 1):
                for field_count in range(config.field_count.minimum or config.field_count.exact or 0,
                                         (config.field_count.maximum or config.field_count.exact or 0) + 1):
                    for family in config.families:
                        quotas[f"{config.kind}/{family}/depth-{depth}/fields-{field_count}"] = config.generation_pool_per_leaf
        return quotas

    @staticmethod
    def _load_task_candidates(database: Any, settings: dict[str, object], catalog_round_id: str) -> list[Any]:
        load = database.load_unbacktested_research_candidates
        try:
            return list(load(settings, catalog_round_id=catalog_round_id))
        except TypeError:
            # Lightweight test doubles and older repository adapters retain
            # the original one-argument API.
            return list(load(settings))

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
        if plan.rolling_capacity_queue:
            return sorted(candidates, key=lambda item: (item.family, item.candidate_id))
        configs = {config.strategy_id: config for config in plan.strategies}
        by_family: dict[str, list[Candidate]] = defaultdict(list)
        for candidate in sorted(candidates, key=lambda item: (item.family, item.candidate_id)):
            config = configs.get(candidate.origin_strategy)
            if config is None:
                config = next(
                    (item for item in plan.strategies if candidate.family.startswith(f"{item.kind}/")),
                    None,
                )
            quota = config.quota_per_leaf_family if config is not None else 0
            if quota > int(selected_counts.get(candidate.family, 0)):
                by_family[candidate.family].append(candidate)
        # Do not trim to the platform batch size here.  This is the full
        # candidate pool presented to the selector; the worker itself sends
        # the selected tasks to the platform in deterministic batches of 8.
        return [candidate for family in sorted(by_family) for candidate in by_family[family]]

    @staticmethod
    def _policy_for_candidates(
        policy: ResearchPolicy,
        candidates: Sequence[Candidate],
        plan: ConstructionPlan,
        selected_counts: dict[str, int],
    ) -> ResearchPolicy:
        if plan.rolling_capacity_queue:
            return replace(policy, max_backtests=plan.platform_batch_size, family_quotas={})
        configs = {config.strategy_id: config for config in plan.strategies}
        quotas: dict[str, int] = {}
        for candidate in candidates:
            config = configs.get(candidate.origin_strategy)
            if config is None:
                config = next(
                    (item for item in plan.strategies if candidate.family.startswith(f"{item.kind}/")),
                    None,
                )
            if config is not None:
                quotas[candidate.family] = max(
                    0, config.quota_per_leaf_family - int(selected_counts.get(candidate.family, 0)),
                )
        return replace(policy, max_backtests=sum(quotas.values()), family_quotas=quotas)

    def _generate_from_qualified_parents(
        self,
        task_id: str,
        database: Any,
        settings: dict[str, object],
        fields: Sequence[Any],
        rows: Sequence[Any],
        plan: ConstructionPlan,
        seed: int,
        *,
        target_stages: dict[str, int] | None = None,
    ) -> tuple[int, list[StrategyStatus]]:
        templates = tuple(database.list_templates(active_only=True))
        generated = 0
        statuses: list[StrategyStatus] = []
        priorities = {config.strategy_id: index for index, config in enumerate(plan.strategies)}
        for row in rows:
            # Construction promotion deliberately uses the exploratory parent
            # gate. Full platform checks belong to review/submission and are
            # still enforced by _queue_signal_candidates.
            if not plan.parent_gate.passes(row.sharpe, row.fitness):
                continue
            parent = Candidate(
                candidate_id=row.alpha_sha or row.expression,
                expression=row.expression,
                family=row.family,
                fields=tuple(row.fields),
                operators=(),
                template_id="qualified-parent",
            )
            identity = row.alpha_sha or row.expression
            next_stage = (target_stages or {}).get(identity, plan.next_stage_for(row.origin_strategy))
            if next_stage is None:
                continue
            for config in plan.strategies_for_stage(next_stage):
                if not config.consumes_parents:
                    continue
                if database.has_parent_strategy_run(settings, parent.candidate_id, config.strategy_id):
                    continue
                parent_config = replace(config, source="qualified_candidates")
                parent_plan = ConstructionPlan(
                    (parent_config,), plan.parent_gate, plan.platform_batch_size, plan.promotion,
                    plan.rolling_capacity_queue, plan.selection_window_batches,
                )
                raw_delay = settings.get("delay")
                delay = int(raw_delay) if isinstance(raw_delay, (int, float, str)) else None
                context = ConstructionContext(
                    tuple(fields), templates, (parent,), seed,
                    region=str(settings.get("region") or ""),
                    universe=str(settings.get("universe") or ""),
                    delay=delay,
                )
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

    @staticmethod
    def _record_promotion(
        database: Any,
        task_id: str,
        settings: dict[str, object],
        row: Any,
        stage: int,
        decision: str,
        reason: str = "",
        details: dict[str, object] | None = None,
    ) -> None:
        record = getattr(database, "record_promotion_decision", None)
        if callable(record):
            record(
                task_id, settings, row.alpha_sha or row.expression, stage,
                decision, reason, details or {},
            )

    def _select_promotion_rows(
        self,
        task_id: str,
        database: Any,
        settings: dict[str, object],
        rows: Sequence[Any],
        plan: ConstructionPlan,
    ) -> tuple[list[Any], list[Any], dict[str, int]]:
        """Select the shared post-backtest survivors and their next stages.

        Quality and PnL-correlation pruning apply to every non-validation
        strategy, including terminal template mode.  All survivors can enter
        the human review queue; only survivors with a later configured stage
        are returned as promotion parents.
        """
        eligible: list[Any] = []
        next_stage_by_sha: dict[str, int] = {}
        decision_stage_by_sha: dict[str, int] = {}
        for row in rows:
            current = next(
                (config for config in plan.strategies if config.strategy_id == row.origin_strategy),
                None,
            )
            if current is None or current.kind == "signal_validation":
                continue
            next_stage = plan.next_stage_for(row.origin_strategy)
            identity = row.alpha_sha or row.expression
            decision_stage_by_sha[identity] = next_stage or current.stage
            if next_stage is not None:
                next_stage_by_sha[identity] = next_stage
            reason = promotion_quality_reason(
                row,
                min_long_short_sum=plan.promotion.quality.min_long_short_sum,
            )
            if reason is None and not plan.parent_gate.passes(row.sharpe, row.fitness):
                reason = "below_parent_gate"
            if reason is not None:
                self._record_promotion(
                    database, task_id, settings, row, decision_stage_by_sha[identity],
                    "reject", reason,
                )
                continue
            eligible.append(row)

        correlation = plan.promotion.correlation
        if correlation.enabled and eligible:
            payloads = [
                {
                    "alpha_id": row.platform_alpha_id,
                    "alpha_sha": row.alpha_sha or row.expression,
                    "sharpe": row.sharpe,
                    "fitness": row.fitness,
                    "margin": row.margin,
                }
                for row in eligible
            ]
            kept, pruned = asyncio.run(multi_channel_correlation_prune(
                payloads,
                MultiChannelCorrelationConfig(
                    channels=correlation.channels,
                    first_band_size=correlation.first_band_size,
                    second_band_size=correlation.second_band_size,
                    first_threshold=correlation.first_threshold,
                    second_threshold=correlation.second_threshold,
                    final_threshold=correlation.final_threshold,
                    min_periods=correlation.min_periods,
                    max_consecutive_flat_days=plan.promotion.quality.max_consecutive_flat_days,
                    max_tail_flat_ratio=plan.promotion.quality.max_tail_flat_ratio,
                ),
                pnl_fetcher=self._cached_pnl_fetcher(database),
            ))
            kept_ids = {str(item["alpha_sha"]) for item in kept}
            rows_by_sha = {row.alpha_sha or row.expression: row for row in eligible}
            for item in pruned:
                identity = str(item["alpha_sha"])
                row = rows_by_sha[identity]
                self._record_promotion(
                    database, task_id, settings, row, decision_stage_by_sha[identity],
                    "reject", str(item.get("prune_reason") or "correlation_pruned"),
                    {
                        "conflicts": item.get("prune_conflicts", []),
                        "channels": list(correlation.channels),
                    },
                )
            eligible = [row for row in eligible if (row.alpha_sha or row.expression) in kept_ids]

        retained = list(eligible)
        promotable = [
            row for row in retained if (row.alpha_sha or row.expression) in next_stage_by_sha
        ]
        stop_target = plan.promotion.early_stop_signal_count
        if stop_target and len(promotable) >= stop_target:
            validation_stages = sorted({
                config.stage for config in plan.strategies
                if config.kind == "signal_validation"
            })
            validation_stage = validation_stages[-1] if validation_stages else None
            for row in promotable:
                identity = row.alpha_sha or row.expression
                self._record_promotion(
                    database, task_id, settings, row, next_stage_by_sha[identity],
                    "early_stop", "signal_target_reached",
                    {"target": stop_target, "validation_stage": validation_stage},
                )
            if validation_stage is None:
                return retained, [], {}
            return retained, promotable, {
                row.alpha_sha or row.expression: validation_stage for row in promotable
            }

        for row in retained:
            identity = row.alpha_sha or row.expression
            self._record_promotion(
                database, task_id, settings, row, decision_stage_by_sha[identity], "promote",
                "" if identity in next_stage_by_sha else "retain_for_review",
            )
        return retained, promotable, {
            row.alpha_sha or row.expression: next_stage_by_sha[row.alpha_sha or row.expression]
            for row in promotable
        }

    @staticmethod
    def _cached_pnl_fetcher(database: Any):
        """Return a cache-first async PnL reader backed by the shared session."""
        load = getattr(database, "get_alpha_pnl_cache", None)
        save = getattr(database, "cache_alpha_pnl", None)
        authenticated = False
        auth_lock = asyncio.Lock()

        async def fetch(alpha_id: str) -> dict[str, object]:
            nonlocal authenticated
            if callable(load):
                cached = load(alpha_id)
                if isinstance(cached, dict):
                    return cached
            from cnhkmcp.untracked.platform_functions import brain_client

            async with auth_lock:
                if not authenticated:
                    await brain_client.ensure_authenticated()
                    authenticated = True
            payload = await brain_client.get_alpha_pnl(alpha_id)
            if not isinstance(payload, dict):
                raise ValueError(f"platform PnL response is not an object: {alpha_id}")
            if callable(save):
                save(alpha_id, payload)
            return payload

        return fetch

    @staticmethod
    def _queue_signal_candidates(database: Any, rows: Sequence[Any]) -> None:
        """Persist qualified results for explicit human optimization review.

        This is a local queue only: it is deliberately separate from the
        submission outbox and has no platform-side effect.
        """
        enqueue = getattr(database, "enqueue_optimization_once", None)
        record_submission = getattr(database, "record_submission_candidate", None)
        for row in rows:
            if (
                not row.checks_passed
                or not is_signal_parent(row)
                or str(row.family).startswith("signal_validation/")
            ):
                continue
            local_id = row.alpha_sha or row.expression
            if callable(enqueue):
                enqueue(
                    local_id,
                    row.expression,
                    sharpe=row.sharpe,
                    fitness=row.fitness,
                    priority=max(1, round(row.sharpe * 100 + row.fitness * 10)),
                    optimization_hints={
                        "source": "research-cycle",
                        "origin_strategy": row.origin_strategy,
                        "family": row.family,
                        "action": "manual_review_before_submission",
                    },
                )
            if callable(record_submission) and row.platform_alpha_id:
                record_submission(
                    row.platform_alpha_id,
                    row.expression,
                    sharpe=row.sharpe,
                    fitness=row.fitness,
                    turnover=row.turnover,
                    margin=row.margin,
                    robustness_status="rank_sign_pending",
                    robustness_notes="terminal rank/sign validation has not completed",
                )

    @staticmethod
    def _evaluate_signal_validations(
        database: Any,
        settings: dict[str, object],
        plan: ConstructionPlan,
    ) -> None:
        load = getattr(database, "load_signal_validation_results", None)
        update = getattr(database, "update_candidate_robustness", None)
        if not plan.promotion.validation.enabled or not callable(load) or not callable(update):
            return
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in load(settings):
            parent_id = str(item.get("parent_alpha_id") or "")
            if parent_id:
                grouped[parent_id].append(item)
        minimum = plan.promotion.validation.minimum_sharpe_ratio
        for parent_id, results in grouped.items():
            ratios: dict[str, float] = {}
            robust_total = robust_passed = robust_failed = 0
            for item in results:
                variant = str(item.get("validation_variant") or "").removeprefix("validation:")
                parent_sharpe = float(item.get("parent_sharpe") or 0.0)
                child_sharpe = float(item.get("child_sharpe") or 0.0)
                ratios[variant] = child_sharpe / parent_sharpe if parent_sharpe > 0 else 0.0
                robust_total = max(robust_total, int(item.get("robust_total") or 0))
                robust_passed = max(robust_passed, int(item.get("robust_passed") or 0))
                robust_failed = max(robust_failed, int(item.get("robust_failed") or 0))
            failed = sorted(name for name, ratio in ratios.items() if ratio < minimum)
            notes = ", ".join(f"{name}={ratio:.3f}" for name, ratio in sorted(ratios.items()))
            if robust_failed:
                update(parent_id, "fail", f"platform robust checks failed={robust_failed}; {notes}")
            elif failed:
                update(parent_id, "fail", f"rank/sign below {minimum:.2f}: {notes}")
            elif {"rank", "sign"}.issubset(ratios):
                if robust_total and robust_passed == robust_total:
                    update(parent_id, "pass", f"rank/sign and platform robust checks passed; {notes}")
                else:
                    update(parent_id, "rank_sign_pass_robust_pending", notes)
            else:
                update(parent_id, "rank_sign_pending", notes or "waiting for rank/sign results")

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
