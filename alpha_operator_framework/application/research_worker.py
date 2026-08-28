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
    """持续或单次扫描就绪的研究实验批次，并调用 Worker 执行。"""

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
            logger.info("轮询开始检测过期实验批次 [当前循环: %d], 轮询间隔=%d 秒", cycles + 1, poll_seconds)
            completed.extend(self.run_once())
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                sleep(poll_seconds)
        return completed


class ResearchBatchWorker:
    """执行单个已提交实验批次的回测、评估、剪枝与知识回填蒸馏的后台工作协处理器。"""

    def __init__(
        self,
        event_store: Any,
        research_repository: Any,
        experiment_repository: Any,
        knowledge_base: KnowledgeBase,
        backtest_gateway: Any,
        knowledge_repository: Any | None = None,
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
        self.telemetry = telemetry
        self.evidence_gateway = evidence_gateway
        self.submission_outbox = submission_outbox
        self.alpha_database = alpha_database

    def _persist_primary_result(self, result: Any, task: Any) -> None:
        if self.alpha_database is None:
            return
        if result.error or not result.platform_alpha_id:
            self.alpha_database.set_expression_status(task.expression, "pending", dict(task.settings))
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
    def _is_retryable_result_error(error: str | None) -> bool:
        """Keep transport and service availability failures in the persisted retry queue."""
        text = (error or "").lower()
        markers = (
            "timeout", "timed out", "connection", "connect", "network", "socket", "dns",
            "reset", "gateway", "unavailable", "temporary", "retry", "rate limit", "429",
            "no platform error detail",
            "超时", "网络", "连接", "限流", "服务不可用",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_rate_limited_result_error(error: str | None) -> bool:
        text = (error or "").lower()
        return "429" in text or "rate limit" in text or "限流" in text

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
        """扫描并处理当前准备好运行的到期实验批次。

        Returns:
            list[ResearchCycleSummary]: 每个到期批次处理完所生成的摘要报告。
        """
        logger.info("扫描准备运行的未决实验批次队列...")
        due_batches = self.experiment_repository.list_due_batches()
        if due_batches:
            logger.info("扫描到 %d 个准备就绪的实验批次", len(due_batches))
        return [self.process_round(batch.batch_id) for batch in due_batches]

    def process_round(self, round_id: str) -> ResearchCycleSummary:
        """处理指定研究回合 ID 的回测执行与评估流水线流程。

        Args:
            round_id: 目标回合标识符。

        Returns:
            ResearchCycleSummary: 处理结果回合摘要报告。
        """
        logger.info("开始消费实验回合 %s...", round_id)
        batch = self.experiment_repository.load_batch(round_id)
        if batch is None:
            logger.error("未找到实验批次记录: %s", round_id)
            raise ValueError(f"missing experiment batch for {round_id}")
        if batch.state is BatchState.EVALUATED:
            logger.info("回合 %s 已处理过评级流程，直接跳过", round_id)
            return self._summary(batch, "COMPLETED", self.knowledge_base.version)
        
        policy = self._policy(round_id)
        round_ = self.research_repository.load_round(round_id)
        if round_ is None:
            logger.error("未找到对应回合的研究配置: %s", round_id)
            raise ValueError(f"missing research round projection for {round_id}")
        
        if batch.state in {BatchState.SUBMITTED, BatchState.PARTIAL_FAILED}:
            self._transition(batch, BatchState.RUNNING)
            logger.info("批次 %s 状态提升至 RUNNING", round_id)
        if batch.state not in {BatchState.RUNNING, BatchState.COMPLETED}:
            raise ValueError(f"batch {round_id} is not runnable: {batch.state}")

        now = datetime.now(UTC)
        missing = [task for task in batch.tasks.values() if task.task_id not in batch.results]
        due = [task for task in missing if task.next_retry_at is None or datetime.fromisoformat(task.next_retry_at) <= now]
        
        logger.info("回合 %s: 共有 %d 个任务配置，其中已完成=%d, 未完成=%d, 满足到期执行条件=%d",
                    round_id, len(batch.tasks), len(batch.results), len(missing), len(due))

        if not due and missing:
            logger.info("暂无满足到期重试条件的回测任务，等待下一次调度轮询...")
            return self._summary(batch, "RETRY_SCHEDULED")
        
        try:
            logger.info("正在执行批量回测，任务大小=%d (分片并发=%d)...", len(due), BACKTEST_BATCH_SIZE)
            results = []
            for offset in range(0, len(due), BACKTEST_BATCH_SIZE):
                shard_results = list(
                    self.backtest_gateway.run_backtests(due[offset:offset + BACKTEST_BATCH_SIZE])
                )
                results.extend(shard_results)
                completed_events = []
                for result in shard_results:
                    task = batch.tasks[result.task_id]
                    self._persist_simulation_result(batch, result)
                    self._persist_primary_result(result, task)
                    if not result.error and result.platform_alpha_id:
                        batch.record_result(result)
                        completed_events.append((result, task))
                self.experiment_repository.save_batch(batch)
                for result, task in completed_events:
                    self._event(EventType.SIMULATION_COMPLETED, round_id, {
                            "task_id": result.task_id, "alpha_id": result.platform_alpha_id,
                            "sharpe": result.sharpe, "fitness": result.fitness,
                            "turnover": result.turnover, "margin": result.margin,
                            "checks_passed": result.checks_passed,
                            "idempotency_key": task.idempotency_key,
                        })
        except Exception as error:
            logger.exception("批量回测在与网关交互时遇到外部连接异常: %s", error)
            if not isinstance(error, (TimeoutError, ConnectionError)) and not self._is_rate_limited(error):
                raise
            retry_due = [task for task in due if task.task_id not in batch.results]
            if not retry_due:
                raise
            attempts = max(task.attempts for task in retry_due) + 1
            delay_seconds = (
                self._retry_after_seconds(error) or self._policy_backoff_seconds(policy, attempts)
                if self._is_rate_limited(error)
                else 0.0
            )
            retry_at = now + timedelta(seconds=delay_seconds)
            task_ids = [task.task_id for task in retry_due]
            batch.record_retry(task_ids, next_retry_at=retry_at.isoformat(), error=str(error))
            self._record_retry_fact(batch, round_id, task_ids, BatchState.PARTIAL_FAILED)
            self._transition(batch, BatchState.PARTIAL_FAILED)
            logger.warning("任务网络故障，安排在 %s (休眠 %.1f 秒) 后重试. 批次状态设为 PARTIAL_FAILED", retry_at.isoformat(), delay_seconds)
            return self._summary(batch, "RETRY_SCHEDULED")

        failures = [result for result in results if result.error]
        if failures:
            logger.warning("本回测周期发现有 %d 个子因子任务在平台端执行失败", len(failures))
            attempts = max(task.attempts for task in due) + 1
            retryable_failures = [result for result in failures if self._is_retryable_result_error(result.error)]
            terminal_failures = [result for result in failures if result not in retryable_failures]
            for result in retryable_failures:
                task = batch.tasks[result.task_id]
                delay_seconds = self._policy_backoff_seconds(policy, attempts) if self._is_rate_limited_result_error(result.error) else 0.0
                batch.record_retry([result.task_id], next_retry_at=(now + timedelta(seconds=delay_seconds)).isoformat(), error=result.error or "platform execution failed")
                self._event(EventType.MONITORING_OBSERVED, round_id, {"task_id": result.task_id, "platform_failure": result.error})
            for result in terminal_failures:
                task = batch.tasks[result.task_id]
                if self.alpha_database is not None:
                    self.alpha_database.set_expression_status(task.expression, "failed", dict(task.settings))
                self._event(EventType.MONITORING_OBSERVED, round_id, {"task_id": result.task_id, "platform_failure": result.error})
            self.experiment_repository.save_batch(batch)
            if terminal_failures:
                self._transition(batch, BatchState.FAILED)
                return self._summary(batch, "FAILED")
            self._transition(batch, BatchState.PARTIAL_FAILED)
            return self._summary(batch, "RETRY_SCHEDULED")

        for result in results:
            task = batch.tasks[result.task_id]
            logger.info("因子 %s 回测正常完成。Sharpe=%.2f, Alpha ID=%s", task.expression, result.sharpe, result.platform_alpha_id)

        if len(batch.results) != len(batch.tasks):
            outstanding = [task.task_id for task in batch.tasks.values() if task.task_id not in batch.results]
            batch.record_retry(
                outstanding, next_retry_at=now.isoformat(), error="gateway returned incomplete results",
            )
            self._record_retry_fact(batch, round_id, outstanding, BatchState.PARTIAL_FAILED)
            self._transition(batch, BatchState.PARTIAL_FAILED)
            logger.warning("网关返回的数据集结果数不完整，部分任务需重新补齐")
            return self._summary(batch, "PARTIAL_FAILED")

        if batch.state is not BatchState.COMPLETED:
            self._transition(batch, BatchState.COMPLETED)
            logger.info("所有子任务全部回测成功，批次 %s 标记为 COMPLETED", round_id)

        from alpha_operator_framework.research.template_correlation import platform_correlation
        correlation_rejected: set[str] = set()
        
        logger.info("开始进行全局及自相关性冲突审查...")
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
                logger.warning("因子 %s 因相关度过高被剔除过滤 (相关度=%.4f > 限额=%.4f)", result.platform_alpha_id, correlation, policy.template_platform_max_correlation)

        logger.info("对回测结果组合运行帕累托优选与信号质量审计...")
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
                logger.info("发现符合优质提交条件的因子 candidate=%s (alpha_id=%s)，开启 6 维证据链路自动审批裁决...", evaluation.task_id, result.platform_alpha_id)
                if self.evidence_gateway is not None:
                    from alpha_operator_framework.knowledge.submission import SubmissionCase

                    case = SubmissionCase.from_result(result, self.evidence_gateway.evidence_for(result))
                    approval = case.approve()
                    self._event(
                        EventType.DECISION_APPROVED if approval.is_approved else EventType.DECISION_REJECTED,
                        round_id,
                        {"task_id": evaluation.task_id, "alpha_id": result.platform_alpha_id, "reason": approval.reason},
                    )
                    logger.info("因子 %s 终审审批决策: 批准=%s, 理由=%s", result.platform_alpha_id, approval.is_approved, approval.reason)
                    if approval.is_approved and self.submission_outbox is not None:
                        self.submission_outbox.enqueue(case)

        templates_by_candidate = {candidate.candidate_id: candidate.template_id for candidate in round_.candidates}
        templates = {task.task_id: templates_by_candidate[task.candidate_id] for task in batch.tasks.values()}
        knowledge = self.knowledge_base.apply_batch(batch, templates)
        
        from alpha_operator_framework.knowledge.distillation import distill_templates
        logger.info("启动优势因子模板逆向蒸馏机制，更新累积经验知识库...")
        distilled = distill_templates(
            batch, min_support=policy.template_min_support,
            min_sharpe=policy.template_min_sharpe, min_fitness=policy.template_min_fitness,
        )
        promoted_templates = []
        if self.alpha_database is not None:
            for template in distilled:
                source_task_id = template.source_task_ids[0]
                persisted = self.alpha_database.save_abstracted_template(
                    expression_template=template.expression_template,
                    support_count=template.support,
                    source_task_ids=template.source_task_ids,
                    example_expression=batch.tasks[source_task_id].expression,
                )
                if persisted:
                    promoted_templates.append(template)
        
        logger.info("本次循环共成功提取出 %d 个高信号特征模板", len(distilled))
        
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
        for template in promoted_templates:
            self._event(EventType.TEMPLATE_PROMOTED, round_id, {
                "expression_template": template.expression_template,
                "support": template.support,
                "source_task_ids": list(template.source_task_ids),
                "policy_version": policy.policy_version,
            })
            
        self._transition(batch, BatchState.EVALUATED)
        if self.telemetry is not None:
            self.telemetry.record_backtests_completed(len(batch.results))
            
        logger.info("=== 实验回合 %s 流水线处理圆满结束 ===", round_id)
        return ResearchCycleSummary(
            status="COMPLETED",
            round_id=round_id,
            selection_audit=[],
            completed_backtests=len(batch.results),
            knowledge_version=knowledge.version,
            distilled_template_count=len(promoted_templates),
            mutation_proposals=propose_mutations(
                batch,
                max_proposals=policy.max_backtests,
                random_source=random.Random(round_.seed),
            ),
        )
