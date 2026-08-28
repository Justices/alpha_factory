"""Closed-loop orchestration across research batches."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Sequence

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest
from alpha_operator_framework.research.construction import AstCandidateBuilder
from alpha_operator_framework.research.optimization import derive_consensus_prune_rules, is_signal_parent
from alpha_operator_framework.research.round import Candidate, ResearchPolicy


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


class ResearchLoopCoordinator:
    """Run base research and its bounded optimization branches until exhaustion."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.builder = AstCandidateBuilder()

    def run(
        self,
        policy: ResearchPolicy,
        fields: Sequence[Any],
        base_candidates: Sequence[Candidate],
        *,
        seed: int,
        execute: bool,
        base_round_id: str = "research-loop",
    ) -> ResearchLoopSummary:
        if not execute:
            raise ValueError("continuous research requires platform execution")
        database = self.runtime.alpha_database
        if database is None:
            raise ValueError("continuous research requires an alpha database")
        settings = self._settings(policy)
        round_ids: list[str] = []
        completed_backtests = pruned_count = generated_count = 0
        initial_candidates = list(base_candidates)
        initial_available = True

        while True:
            pending = database.load_unbacktested_research_candidates(settings)
            optimization = [candidate for candidate in pending if candidate.family.startswith("optimization_")]
            candidates = optimization or pending
            if candidates:
                initial_available = False
            elif initial_available:
                candidates = initial_candidates
                initial_available = False
            if not candidates:
                return ResearchLoopSummary("EXHAUSTED", round_ids, completed_backtests, pruned_count, generated_count)

            round_policy = self._policy_for_candidates(policy, candidates)
            round_id = base_round_id if not round_ids else f"{base_round_id}-{len(round_ids) + 1}"
            planned = self.runtime.plan(ResearchCycleRequest(
                round_id, seed, round_policy, self.runtime.knowledge_base.snapshot(), candidates, True,
            ))
            round_ids.append(planned.round_id)
            summary = self._process_until_terminal(planned.round_id)
            if summary.status != "COMPLETED":
                return ResearchLoopSummary(summary.status, round_ids, completed_backtests, pruned_count, generated_count)
            completed_backtests += summary.completed_backtests

            rows = database.load_completed_expression_results(settings)
            for rule in derive_consensus_prune_rules(rows):
                database.upsert_result_prune_rule(settings, rule.pattern, rule.pattern_type, rule.reason)
            pruned_count += len(database.prune_unbacktested_matching(settings, database.get_result_prune_rules(settings)))
            generated_count += self._generate_missing_stages(database, settings, fields, rows, seed)

    @staticmethod
    def _settings(policy: ResearchPolicy) -> dict[str, object]:
        return {
            "region": policy.region, "universe": policy.universe, "delay": policy.delay,
            "decay": policy.decay, "neutralization": policy.neutralization,
            "truncation": policy.truncation,
        }

    @staticmethod
    def _policy_for_candidates(policy: ResearchPolicy, candidates: Sequence[Candidate]) -> ResearchPolicy:
        """Constrain one persisted round to a single dynamic-pruning slice."""
        families = sorted({candidate.family for candidate in candidates})
        capacity = min(RESEARCH_SHARD_SIZE, len(candidates))
        base_quota, remainder = divmod(capacity, max(1, len(families)))
        # Explicit family quotas override max_backtests in the selector.  Their
        # sum must therefore be the slice capacity, not the source policy's
        # per-family quota (which previously expanded a slice to dozens).
        quotas = {
            family: base_quota + (1 if index < remainder else 0)
            for index, family in enumerate(families)
        }
        return replace(
            policy,
            max_backtests=capacity,
            family_quotas=quotas,
        )

    def _generate_missing_stages(
        self,
        database: Any,
        settings: dict[str, object],
        fields: Sequence[Any],
        rows: Sequence[Any],
        seed: int,
    ) -> int:
        templates = database.list_templates(active_only=True)
        generated = 0
        for row in rows:
            if not is_signal_parent(row):
                continue
            parent = Candidate(
                candidate_id=row.alpha_sha or row.expression, expression=row.expression, family=row.family,
                fields=tuple(row.fields), operators=(), template_id="signal-parent",
            )
            if row.family.startswith("optimization_dimension2"):
                continue
            if row.family.startswith("optimization_order2"):
                stage = "dimension2"
                children = self.builder.build_dimension2(parent, fields, templates, seed=seed)
            else:
                stage = "order2"
                children = self.builder.build_order2(parent, templates)
            catalog_children = []
            new_lineage_count = 0
            for child in children:
                child_sha = database.compute_alpha_sha(child.expression, settings)
                database.insert_expression(
                    child.expression, settings, expression_origin=f"optimization_{stage}",
                    fields=list(child.fields), status="generated",
                )
                catalog_children.append(child)
                if database.record_optimization_lineage(settings, parent.candidate_id, child_sha, stage):
                    new_lineage_count += 1
            if catalog_children:
                database.catalog_research_candidates(
                    f"optimization-{stage}-{parent.candidate_id[:12]}", catalog_children, settings,
                )
                generated += new_lineage_count
        return generated

    def _process_until_terminal(self, round_id: str) -> Any:
        """Keep processing one persisted batch until it completes or terminally fails."""
        while True:
            summary = self.runtime.process_round(round_id)
            if summary.status not in RETRYABLE_STATUSES:
                return summary
            self._wait_for_retry(round_id)

    def _wait_for_retry(self, round_id: str) -> None:
        """Wait only until the next persisted retry deadline, then re-read the batch state."""
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
