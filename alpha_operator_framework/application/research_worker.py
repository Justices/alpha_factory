"""Event-led, restart-safe execution worker for submitted research batches."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import replace
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any

logger = logging.getLogger(__name__)

BACKTEST_BATCH_SIZE = 8

from alpha_operator_framework.application.research_cycle import ResearchCycleSummary
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.experiment.evaluation import evaluate_batch
from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.mutation import propose_mutations
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import ResearchPolicy


class ResearchWorkerScheduler:
    """Runs due-batch scans once or continuously without owning persistence details."""

    def __init__(self, worker: Any) -> None:
        """初始化调度器。

        Args:
            worker: 实际执行批次处理的 ResearchBatchWorker 实例。
        """
        self.worker = worker

    def run_once(self) -> list[ResearchCycleSummary]:
        """执行一次扫描并处理所有到期批次。

        Returns:
            本次扫描处理完成的 ResearchCycleSummary 列表。
        """
        return self.worker.process_due_batches()

    def watch(
        self,
        *,
        poll_seconds: int = 30,
        sleep: Callable[[float], None] = time.sleep,
        max_cycles: int | None = None,
    ) -> list[ResearchCycleSummary]:
        """持续轮询，直到达到最大循环次数为止。

        Args:
            poll_seconds: 每次轮询之间的休眠秒数，必须为正整数。
            sleep: 休眠函数，默认使用 time.sleep，可在测试中替换。
            max_cycles: 最大轮询次数；为 None 时无限循环。

        Returns:
            所有轮次中处理完成的 ResearchCycleSummary 列表。

        Raises:
            ValueError: 当 poll_seconds 小于 1 时抛出。
        """
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be positive")
        completed: list[ResearchCycleSummary] = []
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            logger.debug("轮询第 %d 轮开始，poll_seconds=%d", cycles + 1, poll_seconds)
            completed.extend(self.run_once())
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                sleep(poll_seconds)
        return completed


class ResearchBatchWorker:
    """Consumes one submitted batch; snapshots are projections, events retain its audit trail."""

    def __init__(
        self,
        event_store: Any,
        research_repository: Any,
        experiment_repository: Any,
        knowledge_base: KnowledgeBase,
        backtest_gateway: Any,
        knowledge_repository: Any | None = None,
        template_repository: Any | None = None,
        telemetry: Any | None = None,
        evidence_gateway: Any | None = None,
        submission_outbox: Any | None = None,
        alpha_database: Any | None = None,
    ) -> None:
        self.event_store = event_store
        self.research_repository = research_repository
        self.experiment_repository = experiment_repository
        self.knowledge_base = knowledge_base
        self.backtest_gateway = backtest_gateway
        self.knowledge_repository = knowledge_repository
        self.template_repository = template_repository
        self.telemetry = telemetry
        self.evidence_gateway = evidence_gateway
        self.submission_outbox = submission_outbox
        self.alpha_database = alpha_database

    def _persist_primary_result(self, result: Any, task: Any) -> None:
        if self.alpha_database is None:
            return
        if result.error:
            self.alpha_database.set_expression_status(task.expression, "failed", dict(task.settings))
            return
        if not result.platform_alpha_id:
            self.alpha_database.set_expression_status(task.expression, "failed", dict(task.settings))
            return
        payload = dict(result.raw_details or {})
        payload.setdefault("id", result.platform_alpha_id)
        payload.setdefault("expression", task.expression)
        payload.setdefault("settings", dict(task.settings))
        payload.setdefault("is", {"sharpe": result.sharpe, "fitness": result.fitness, "turnover": result.turnover, "margin": result.margin, "checks": []})
        self.alpha_database.save_result_with_checks(result.platform_alpha_id, payload, dict(task.settings))
        self.alpha_database.set_expression_status(task.expression, "completed", dict(task.settings))

    def _persist_simulation_result(self, batch: Any, result: Any) -> None:
        if self.alpha_database is None or batch.storage_batch_id is None:
            return
        sequence_no = list(batch.tasks).index(result.task_id)
        failed = bool(result.error or not result.platform_alpha_id)
        self.alpha_database.record_simulation_result(
            batch.storage_batch_id, sequence_no,
            status="failed" if failed else "completed",
            alpha_id=result.platform_alpha_id or "",
            result=dict(result.raw_details or {}),
            error_message=result.error or ("platform returned no alpha ID" if failed else ""),
        )

    def _event(self, event_type: EventType, round_id: str, payload: dict[str, Any]) -> int:
        return self.event_store.append(Event.create(event_type, round_id, payload, actor="worker:research-batch"))

    def _policy(self, round_id: str) -> ResearchPolicy:
        for event in self.event_store.read_stream(round_id):
            if event.event_type is EventType.POLICY_CREATED:
                payload = dict(event.payload["policy"])
                payload["prohibited_patterns"] = tuple(payload.get("prohibited_patterns", ()))
                return ResearchPolicy(**payload)
        raise ValueError(f"missing PolicyCreated event for {round_id}")

    def _transition(self, batch: Any, target: BatchState) -> None:
        record = transition(batch, target)
        if not record.accepted:
            raise ValueError(f"invalid batch transition {record.from_state} -> {target}")
        self.experiment_repository.save_batch(batch)
        if self.telemetry is not None:
            self.telemetry.record_transition(batch, record)

    def _summary(self, batch: Any, status: str, knowledge_version: int = 0, templates: int = 0) -> ResearchCycleSummary:
        return ResearchCycleSummary(
            status=status,
            round_id=batch.batch_id,
            selection_audit=[],
            completed_backtests=len(batch.results),
            knowledge_version=knowledge_version,
            distilled_template_count=templates,
            mutation_proposals=[],
        )

    def _record_retry_fact(self, batch: Any, round_id: str, task_ids: list[str], state: BatchState) -> None:
        """Persist the retry projection facts required to rebuild a batch."""
        self._event(EventType.MONITORING_OBSERVED, round_id, {"retry": {
            "state": state.value,
            "tasks": [
                {
                    "task_id": task_id,
                    "attempts": batch.tasks[task_id].attempts,
                    "next_retry_at": batch.tasks[task_id].next_retry_at,
                    "last_error": batch.tasks[task_id].last_error,
                }
                for task_id in task_ids
            ],
        }})

    @staticmethod
    def _is_rate_limited(error: Exception) -> bool:
        response = getattr(error, "response", None)
        status_code = getattr(error, "status_code", getattr(response, "status_code", None))
        return status_code == 429 or "429" in str(error)

    @staticmethod
    def _retry_after_seconds(error: Exception) -> float | None:
        response = getattr(error, "response", None)
        retry_after = getattr(error, "retry_after", None)
        if retry_after is None:
            headers = getattr(error, "headers", None) or getattr(response, "headers", None)
            retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
        try:
            seconds = float(retry_after)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(retry_after))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                seconds = (retry_at - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        return seconds if isfinite(seconds) and seconds > 0 else None

    @staticmethod
    def _policy_backoff_seconds(policy: ResearchPolicy, attempts: int) -> float:
        if not policy.retry_backoff_seconds:
            return 0.0
        index = min(attempts - 1, len(policy.retry_backoff_seconds) - 1)
        return policy.retry_backoff_seconds[index]

    def process_due_batches(self) -> list[ResearchCycleSummary]:
        """One scheduler tick: process each persisted batch whose retry is due."""
        return [self.process_round(batch.batch_id) for batch in self.experiment_repository.list_due_batches()]

    def process_round(self, round_id: str) -> ResearchCycleSummary:
        batch = self.experiment_repository.load_batch(round_id)
        if batch is None:
            raise ValueError(f"missing experiment batch for {round_id}")
        if batch.state is BatchState.EVALUATED:
            return self._summary(batch, "COMPLETED", self.knowledge_base.version)
        policy = self._policy(round_id)
        round_ = self.research_repository.load_round(round_id)
        if round_ is None:
            raise ValueError(f"missing research round projection for {round_id}")
        if batch.state in {BatchState.SUBMITTED, BatchState.PARTIAL_FAILED}:
            self._transition(batch, BatchState.RUNNING)
        if batch.state not in {BatchState.RUNNING, BatchState.COMPLETED}:
            raise ValueError(f"batch {round_id} is not runnable: {batch.state}")

        now = datetime.now(UTC)
        missing = [task for task in batch.tasks.values() if task.task_id not in batch.results]
        due = [task for task in missing if task.next_retry_at is None or datetime.fromisoformat(task.next_retry_at) <= now]
        if not due and missing:
            return self._summary(batch, "RETRY_SCHEDULED")
        try:
            results = [
                result
                for offset in range(0, len(due), BACKTEST_BATCH_SIZE)
                for result in self.backtest_gateway.run_backtests(due[offset:offset + BACKTEST_BATCH_SIZE])
            ]
        except Exception as error:
            if not isinstance(error, (TimeoutError, ConnectionError)) and not self._is_rate_limited(error):
                raise
            attempts = max(task.attempts for task in due) + 1
            if attempts >= policy.max_retry_attempts:
                task_ids = [task.task_id for task in due]
                batch.record_retry(task_ids, next_retry_at=now.isoformat(), error=str(error))
                self._record_retry_fact(batch, round_id, task_ids, BatchState.FAILED)
                self._transition(batch, BatchState.FAILED)
                self._event(EventType.MONITORING_OBSERVED, round_id, {"alert": "retry_budget_exhausted", "error": str(error)[:1000]})
                return self._summary(batch, "FAILED")
            delay_seconds = self._retry_after_seconds(error) or self._policy_backoff_seconds(policy, attempts)
            retry_at = now + timedelta(seconds=delay_seconds)
            task_ids = [task.task_id for task in due]
            batch.record_retry(task_ids, next_retry_at=retry_at.isoformat(), error=str(error))
            self._record_retry_fact(batch, round_id, task_ids, BatchState.PARTIAL_FAILED)
            self._transition(batch, BatchState.PARTIAL_FAILED)
            return self._summary(batch, "RETRY_SCHEDULED")
        failures = [result for result in results if result.error]
        if failures:
            attempts = max(task.attempts for task in due) + 1
            for result in failures:
                task = batch.tasks[result.task_id]
                self._persist_simulation_result(batch, result)
                self._persist_primary_result(result, task)
                batch.record_retry([result.task_id], next_retry_at=(now + timedelta(seconds=self._policy_backoff_seconds(policy, attempts))).isoformat(), error=result.error or "platform execution failed")
                self._event(EventType.MONITORING_OBSERVED, round_id, {"task_id": result.task_id, "platform_failure": result.error})
            self.experiment_repository.save_batch(batch)
            self._transition(batch, BatchState.FAILED if attempts >= policy.max_retry_attempts else BatchState.PARTIAL_FAILED)
            return self._summary(batch, "FAILED" if attempts >= policy.max_retry_attempts else "RETRY_SCHEDULED")
        for result in results:
            batch.record_result(result)
            task = batch.tasks[result.task_id]
            self._persist_simulation_result(batch, result)
            self._persist_primary_result(result, task)
            self._event(EventType.SIMULATION_COMPLETED, round_id, {
                "task_id": result.task_id, "alpha_id": result.platform_alpha_id,
                "sharpe": result.sharpe, "fitness": result.fitness, "turnover": result.turnover,
                "margin": result.margin, "checks_passed": result.checks_passed,
                "idempotency_key": task.idempotency_key,
            })
        if len(batch.results) != len(batch.tasks):
            outstanding = [task.task_id for task in batch.tasks.values() if task.task_id not in batch.results]
            batch.record_retry(
                outstanding, next_retry_at=now.isoformat(), error="gateway returned incomplete results",
            )
            self._record_retry_fact(batch, round_id, outstanding, BatchState.PARTIAL_FAILED)
            self._transition(batch, BatchState.PARTIAL_FAILED)
            return self._summary(batch, "PARTIAL_FAILED")

        if batch.state is not BatchState.COMPLETED:
            self._transition(batch, BatchState.COMPLETED)
        from alpha_operator_framework.research.template_correlation import platform_correlation
        correlation_rejected: set[str] = set()
        for task_id, result in batch.results.items():
            correlation = platform_correlation(result.self_correlation, result.production_correlation)
            passed = correlation <= policy.template_platform_max_correlation
            self._event(EventType.CORRELATION_CHECKED, round_id, {"task_id": task_id, "alpha_id": result.platform_alpha_id, "self_correlation": result.self_correlation, "production_correlation": result.production_correlation, "max_abs_correlation": correlation, "threshold": policy.template_platform_max_correlation, "passed": passed})
            if not passed:
                correlation_rejected.add(task_id)
                evaluation = batch.evaluations.get(task_id)
                if evaluation is not None:
                    batch.record_evaluation(replace(evaluation, pruned=True))
                self._event(EventType.CANDIDATE_RETIRED, round_id, {"task_id": task_id, "reason": "platform_correlation", "max_abs_correlation": correlation, "threshold": policy.template_platform_max_correlation})
        for evaluation in evaluate_batch(batch, policy):
            if evaluation.task_id in correlation_rejected:
                evaluation = replace(evaluation, pruned=True)
            batch.record_evaluation(evaluation)
            self._event(EventType.VALIDATION_COMPUTED, round_id, {
                "task_id": evaluation.task_id, "verdict": evaluation.verdict,
                "pareto_rank": evaluation.pareto_rank, "pruned": evaluation.pruned,
            })
            if evaluation.verdict == "READY" and not evaluation.pruned:
                result = batch.results[evaluation.task_id]
                self._event(EventType.DECISION_PROPOSED, round_id, {
                    "task_id": evaluation.task_id, "alpha_id": result.platform_alpha_id,
                    "pareto_rank": evaluation.pareto_rank, "decision_state": "PENDING_EVIDENCE",
                })
                if self.evidence_gateway is not None:
                    from alpha_operator_framework.knowledge.submission import SubmissionCase

                    case = SubmissionCase.from_result(result, self.evidence_gateway.evidence_for(result))
                    approval = case.approve()
                    self._event(
                        EventType.DECISION_APPROVED if approval.is_approved else EventType.DECISION_REJECTED,
                        round_id,
                        {"task_id": evaluation.task_id, "alpha_id": result.platform_alpha_id, "reason": approval.reason},
                    )
                    if approval.is_approved and self.submission_outbox is not None:
                        self.submission_outbox.enqueue(case)
        templates_by_candidate = {candidate.candidate_id: candidate.template_id for candidate in round_.candidates}
        templates = {task.task_id: templates_by_candidate[task.candidate_id] for task in batch.tasks.values()}
        knowledge = self.knowledge_base.apply_batch(batch, templates)
        from alpha_operator_framework.knowledge.distillation import distill_templates
        distilled = distill_templates(
            batch, min_support=policy.template_min_support,
            min_sharpe=policy.template_min_sharpe, min_fitness=policy.template_min_fitness,
        )
        if self.alpha_database is not None:
            for template in distilled:
                source_task_id = template.source_task_ids[0]
                self.alpha_database.save_abstracted_template(
                    expression_template=template.expression_template,
                    support_count=template.support,
                    example_expression=batch.tasks[source_task_id].expression,
                )
        knowledge_offset = self._event(EventType.MONITORING_OBSERVED, round_id, {"knowledge": {
            "version": self.knowledge_base.version,
            "field_scores": self.knowledge_base.field_scores,
            "operator_scores": self.knowledge_base.operator_scores,
            "template_scores": self.knowledge_base.template_scores,
            "rejected_templates": sorted(self.knowledge_base.rejected_templates),
            "field_trials": self.knowledge_base.field_trials,
        }})
        if self.knowledge_repository is not None:
            self.knowledge_repository.save(
                self.knowledge_base, round_id=round_id, policy_version=policy.policy_version,
                event_offset=knowledge_offset,
            )
        if self.template_repository is not None:
            self.template_repository.promote(distilled)
        for template in distilled:
            self._event(EventType.TEMPLATE_PROMOTED, round_id, {
                "expression_template": template.expression_template,
                "support": template.support,
                "source_task_ids": list(template.source_task_ids),
                "policy_version": policy.policy_version,
            })
        self._transition(batch, BatchState.EVALUATED)
        if self.telemetry is not None:
            self.telemetry.record_backtests_completed(len(batch.results))
        return ResearchCycleSummary(
            status="COMPLETED",
            round_id=round_id,
            selection_audit=[],
            completed_backtests=len(batch.results),
            knowledge_version=knowledge.version,
            distilled_template_count=len(distilled),
            mutation_proposals=propose_mutations(
                batch,
                max_proposals=policy.max_backtests,
                random_source=random.Random(round_.seed),
            ),
        )
