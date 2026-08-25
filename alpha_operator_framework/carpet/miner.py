"""Orchestration entrypoint for stratified carpet mining."""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from alpha_operator_framework.carpet.candidate_generation import generate_candidate_expressions_by_category
from alpha_operator_framework.carpet.field_catalog import load_available_fields
from alpha_operator_framework.carpet.models import CarpetMiningConfig, CarpetMiningResult
from alpha_operator_framework.carpet.sampling import sample_cohort
from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge, JudgeReport
from alpha_operator_framework.platform.platform_simulator import BrainPlatformSimulator, PlatformAlphaResult

logger = logging.getLogger(__name__)


class StratifiedCarpetMiner:
    """Coordinate field loading, candidate generation, sampling, and mining stages."""

    def __init__(self, config: CarpetMiningConfig, db: Optional[AlphaDatabase] = None):
        self.config = config
        self.db = db or AlphaDatabase()
        self.simulator = BrainPlatformSimulator()
        if config.seed is not None:
            random.seed(config.seed)

    def load_available_fields(self) -> List[Dict[str, object]]:
        return load_available_fields(self.config)

    def generate_candidate_expressions_by_category(self, fields: List[Dict[str, object]]) -> Dict[str, List[Task]]:
        return generate_candidate_expressions_by_category(self.config, self.db, fields)

    def sample_cohort(self, categorized_tasks: Dict[str, List[Task]]) -> List[Task]:
        return sample_cohort(self.config, self.db, categorized_tasks)

    def run_batch_simulation_and_persist(self, cohort: List[Task]) -> List[PlatformAlphaResult]:
        from alpha_operator_framework.carpet.simulation import run_batch_simulation_and_persist
        return run_batch_simulation_and_persist(self, cohort)

    def prune_zero_signal_families(self, cohort: List[Task], results: List[PlatformAlphaResult]) -> List[str]:
        from alpha_operator_framework.carpet.optimization import prune_zero_signal_families
        return prune_zero_signal_families(self, cohort, results)

    def optimize_positive_signals(self, results: List[PlatformAlphaResult]) -> List[PlatformAlphaResult]:
        from alpha_operator_framework.carpet.optimization import optimize_positive_signals
        return optimize_positive_signals(self, results)

    def distill_and_persist_winning_templates(self, final_reports: List[JudgeReport]) -> List[str]:
        from alpha_operator_framework.carpet.distillation import distill_and_persist_winning_templates
        return distill_and_persist_winning_templates(self, final_reports)

    def run(self) -> CarpetMiningResult:
        """Execute the complete mining workflow."""
        started_at = time.time()
        logger.info("=== 启动地毯式挖掘流程 (%s / %s) ===", self.config.region, self.config.universe)
        fields = self.load_available_fields()
        if not fields:
            raise RuntimeError("未在指定数据集中找到有效字段，请检查数据集名称与区域配置")
        categorized_tasks = self.generate_candidate_expressions_by_category(fields)
        cohort = self.sample_cohort(categorized_tasks)
        first_gen_results = self.run_batch_simulation_and_persist(cohort)
        pruned_families = self.prune_zero_signal_families(cohort, first_gen_results)
        optimized_results = self.optimize_positive_signals(first_gen_results)
        details = [result.raw_details for result in first_gen_results + optimized_results if result.raw_details]
        ranked_reports = AlphaJudge().rank_candidates(details) if details else []
        distilled_templates = self.distill_and_persist_winning_templates(ranked_reports)
        total_generated = sum(len(tasks) for tasks in categorized_tasks.values())
        all_ids = [result.alpha_id for result in first_gen_results + optimized_results if result.alpha_id and not result.alpha_id.startswith("FAILED_")]
        self._record_backtests(total_generated, len(cohort))
        return CarpetMiningResult(
            config=self.config,
            total_expressions_generated=total_generated,
            sampled_cohort_size=len(cohort),
            categories_tested=list(categorized_tasks),
            first_gen_results=first_gen_results,
            pruned_families=pruned_families,
            optimized_results=optimized_results,
            all_persisted_ids=all_ids,
            ranked_reports=ranked_reports,
            elapsed_seconds=time.time() - started_at,
            distilled_templates=distilled_templates,
        )

    def _record_backtests(self, expression_count: int, backtest_count: int) -> None:
        if not (self.db and hasattr(self.db, "upsert_backtest_record")):
            return
        for dataset in self.config.datasets:
            try:
                self.db.upsert_backtest_record(
                    region=self.config.region, universe=self.config.universe, delay=self.config.delay,
                    dataset_id=dataset, strategy="carpet_mining", expression_count=expression_count,
                    backtest_count=backtest_count,
                )
            except Exception:
                pass


def _run_stratified_carpet_mining_with(miner_type, region: str = "GBR", universe: str = "TOP700", datasets: Optional[Sequence[str]] = None, sample_per_family: int = 4, batch_size: int = 5, delay: int = 1, decay: int = 12, neutralization: str = "SUBINDUSTRY", truncation: float = 0.08, execute: bool = True, seed: Optional[int] = None, output_report_path: Optional[str] = None) -> CarpetMiningResult:
    config = CarpetMiningConfig(region=region, universe=universe, delay=delay, datasets=list(datasets) if datasets else ["insider_agg_matrix", "pattern_scores", "fundamental31", "risk60"], sample_per_family=sample_per_family, batch_size=batch_size, decay=decay, neutralization=neutralization, truncation=truncation, execute=execute, seed=seed)
    result = miner_type(config).run()
    if output_report_path:
        report_path = Path(output_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(result.summary_markdown(), encoding="utf-8")
        logger.info("已导出研报到: %s", report_path)
    return result


def run_stratified_carpet_mining(region: str = "GBR", universe: str = "TOP700", datasets: Optional[Sequence[str]] = None, sample_per_family: int = 4, batch_size: int = 5, delay: int = 1, decay: int = 12, neutralization: str = "SUBINDUSTRY", truncation: float = 0.08, execute: bool = True, seed: Optional[int] = None, output_report_path: Optional[str] = None) -> CarpetMiningResult:
    return _run_stratified_carpet_mining_with(StratifiedCarpetMiner, region, universe, datasets, sample_per_family, batch_size, delay, decay, neutralization, truncation, execute, seed, output_report_path)
