"""Simulation and persistence stage for carpet mining."""

from __future__ import annotations

import logging
from typing import List

from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge
from alpha_operator_framework.platform.platform_simulator import PlatformAlphaResult
from alpha_operator_framework.research.db_persister import persist_research_pipeline_results

logger = logging.getLogger(__name__)


def run_batch_simulation_and_persist(
    miner,
    cohort: List[Task],
) -> List[PlatformAlphaResult]:
    """分批推进平台回测，并实现每一批结束即时流式持久化入库."""
    if not miner.config.execute:
        logger.info("当前为 Dry-Run 模式，跳过真实平台提交")
        return []

    settings = {
        "region": miner.config.region,
        "universe": miner.config.universe,
        "delay": miner.config.delay,
        "decay": miner.config.decay,
        "neutralization": miner.config.neutralization,
        "truncation": miner.config.truncation,
        "unitHandling": miner.config.unit_handling,
        "nanHandling": miner.config.nan_handling,
    }

    all_results: List[PlatformAlphaResult] = []
    batch_size = miner.config.batch_size
    total_batches = (len(cohort) + batch_size - 1) // batch_size

    logger.info(f"开始执行真实平台分批回测: 共 {len(cohort)} 个任务，切分为 {total_batches} 批...")

    for b_idx in range(total_batches):
        chunk = cohort[b_idx * batch_size : (b_idx + 1) * batch_size]
        print(f"\n🚀 [批次 {b_idx + 1}/{total_batches}] 正在提交 {len(chunk)} 个 Alpha 到 WorldQuant BRAIN...")

        # 1. 提交与轮询本批次
        batch_results = miner.simulator.simulate_batch(
            tasks=chunk,
            settings=settings,
            poll_interval=4.0,
            timeout=300.0,
        )
        all_results.extend(batch_results)

        # 2. 本批次实时 AlphaJudge 裁决
        valid_details = [r.raw_details for r in batch_results if r.raw_details]
        judge = AlphaJudge()
        reports = judge.rank_candidates(valid_details) if valid_details else []
        ranked_cands = [
            {
                "alpha_id": rep.alpha_id,
                "expression": rep.expression,
                "verdict": rep.verdict.value,
                "priority_score": rep.priority_score,
                "metrics": rep.metrics,
                "recommendation": rep.actionable_recommendations[0] if rep.actionable_recommendations else "",
            }
            for rep in reports
        ]

        # 3. ★ 实时持久化落库 (alpha_expressions, alpha_details, alpha_checks)
        ds_names = ",".join(miner.config.datasets)
        stats = persist_research_pipeline_results(
            db=miner.db,
            paper_title=f"GBR Carpet Mining ({ds_names})",
            tasks=chunk,
            settings=settings,
            platform_results=batch_results,
            ranked_candidates=ranked_cands,
            source_type="carpet_mining",
        )
        print(f"  💾 批次 {b_idx + 1} 实时落库成功: 写入 {stats.get('inserted_expressions', 0)} 条表达式, {stats.get('saved_details', 0)} 条回测详情")

        # 打印本批次优胜者
        for idx, r in enumerate(batch_results, 1):
            if r.alpha_id and not r.alpha_id.startswith("FAILED_"):
                print(f"    - Alpha ID: {r.alpha_id} | Sharpe: {r.sharpe:.2f} | Fitness: {r.fitness:.2f} | 换手率: {r.turnover:.1%} | 年化: {r.annualized_return:.2%}")

    return all_results



__all__ = ["run_batch_simulation_and_persist"]

