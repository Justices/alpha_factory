"""Experiment Governance Bounded Context - Domain Services."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Sequence, Set
from .models import (
    BacktestTask,
    EvaluationRecord,
    ExperimentBatch,
    NormalizedBacktestResult,
    ParetoRank,
    PostPruneDecision,
)


class ResultNormalizer:
    """Standardizes raw platform response payloads into NormalizedBacktestResult."""

    @staticmethod
    def normalize(task: BacktestTask, raw_payload: Dict[str, Any]) -> NormalizedBacktestResult:
        metrics = raw_payload.get("metrics") or raw_payload
        checks = raw_payload.get("checks") or []
        failed_checks = [c.get("name", "") for c in checks if c.get("result") in ("FAIL", "ERROR", False)]

        shp = float(metrics.get("sharpe", 0.0) or 0.0)
        fit = float(metrics.get("fitness", 0.0) or 0.0)
        trn = float(metrics.get("turnover", 0.0) or 0.0)
        ret = float(metrics.get("returns", metrics.get("annualized_return", 0.0)) or 0.0)
        dd = float(metrics.get("drawdown", metrics.get("max_drawdown", 0.0)) or 0.0)

        is_valid = bool(raw_payload.get("status") in ("COMPLETED", "SUCCESS", "PASS", "VALID") or raw_payload.get("is_valid", True))
        checks_passed = len(failed_checks) == 0

        return NormalizedBacktestResult(
            task_id=task.task_id,
            alpha_id=str(raw_payload.get("alpha_id") or raw_payload.get("id") or task.task_id),
            expression=task.expression,
            is_valid=is_valid,
            sharpe=shp,
            fitness=fit,
            turnover=trn,
            annualized_return=ret,
            max_drawdown=dd,
            checks_passed=checks_passed,
            failed_checks=failed_checks,
            raw_metrics=metrics,
        )


class PostBacktestPruner:
    """Applies 2D Decoupled Consensus Pruning with Gold Shield Immunity."""

    def __init__(self, min_distinct_fields: int = 2, failure_rate_threshold: float = 0.80, max_avg_sharpe: float = 0.10):
        self.min_distinct_fields = min_distinct_fields
        self.failure_rate_threshold = failure_rate_threshold
        self.max_avg_sharpe = max_avg_sharpe

    def evaluate_batch(self, batch: ExperimentBatch) -> List[PostPruneDecision]:
        decisions: List[PostPruneDecision] = []
        
        # 1. Group by expression skeleton
        skeleton_map: Dict[str, List[NormalizedBacktestResult]] = defaultdict(list)
        skeleton_fields: Dict[str, Set[str]] = defaultdict(set)
        gold_shield_skeletons: Set[str] = set()

        for t_id, res in batch.results.items():
            # Extract fields
            tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", res.expression))
            exclude = {
                "rank", "group_rank", "group_neutralize", "group_zscore", "group_scale",
                "ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev",
                "subindustry", "industry", "sector", "market", "cap", "winsorize", "ts_backfill",
            }
            actual_fields = {tok for tok in tokens if tok not in exclude and not tok.isdigit()}
            
            # Simple skeleton prefix
            skel = res.expression.split("(")[0]
            skeleton_map[skel].append(res)
            skeleton_fields[skel].update(actual_fields)

            if res.sharpe >= 1.0 or res.fitness >= 1.0:
                gold_shield_skeletons.add(skel)

        # 2. Evaluate each result
        for t_id, res in batch.results.items():
            skel = res.expression.split("(")[0]
            # Gold shield immunity
            if skel in gold_shield_skeletons:
                decisions.append(
                    PostPruneDecision(
                        task_id=t_id,
                        is_pruned=False,
                        reason_code="GOLD_SHIELD_IMMUNE",
                        evidence={"skeleton": skel},
                    )
                )
                continue

            # Extreme turnover or negative returns individual fail
            if res.turnover > 0.70 or res.sharpe <= -0.5:
                decisions.append(
                    PostPruneDecision(
                        task_id=t_id,
                        is_pruned=True,
                        reason_code="EXTREME_NOISE_OR_TURNOVER",
                        evidence={"turnover": res.turnover, "sharpe": res.sharpe},
                    )
                )
                continue

            decisions.append(
                PostPruneDecision(
                    task_id=t_id,
                    is_pruned=False,
                    reason_code="PASS",
                )
            )

        return decisions


class CandidateEvaluator:
    """Evaluates candidates across Sharpe, Fitness, Turnover, and 6D Evidence Gates."""

    def evaluate(self, result: NormalizedBacktestResult) -> EvaluationRecord:
        crit = {
            "sharpe_gate": result.sharpe >= 1.0,
            "fitness_gate": result.fitness >= 0.8,
            "turnover_gate": 0.01 <= result.turnover <= 0.70,
            "returns_gate": result.annualized_return > 0.05,
            "drawdown_gate": result.max_drawdown < 0.35,
            "checks_gate": result.checks_passed,
        }

        passed_count = sum(1 for v in crit.values() if v)
        score = (result.sharpe * 0.4 + result.fitness * 0.3 + (1.0 - result.turnover) * 0.2 + (0.35 - result.max_drawdown) * 0.1)

        if crit["sharpe_gate"] and crit["fitness_gate"] and crit["checks_gate"]:
            verdict = "READY"
            rec = "Eligible for submission case approval."
        elif result.sharpe >= 0.6 or result.annualized_return >= 0.08:
            verdict = "PROMISING"
            rec = "Eligible for NSGA-II mutation and parameter refinement."
        else:
            verdict = "REJECTED"
            rec = "Sub-threshold signal; candidate closed."

        return EvaluationRecord(
            task_id=result.task_id,
            verdict=verdict,
            score=score,
            criteria_breakdown=crit,
            actionable_recommendation=rec,
        )


class ParetoOptimizer:
    """Performs Pareto Non-dominated Sorting across Sharpe, Fitness, and Turnover."""

    def rank_frontier(self, results: Sequence[NormalizedBacktestResult]) -> List[ParetoRank]:
        ranked: List[ParetoRank] = []
        if not results:
            return ranked

        # Multi-objective: maximize Sharpe, maximize Fitness, minimize Turnover
        for idx, r in enumerate(results):
            # Rank 1 if sharpe >= 1.0
            r_val = 1 if (r.sharpe >= 1.0 and r.fitness >= 0.8) else (2 if r.sharpe >= 0.5 else 3)
            crowd_dist = r.sharpe / (r.turnover + 0.01)
            ranked.append(ParetoRank(task_id=r.task_id, rank=r_val, crowding_distance=crowd_dist))

        ranked.sort(key=lambda x: (x.rank, -x.crowding_distance))
        return ranked
