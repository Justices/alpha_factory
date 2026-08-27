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
    """地毯式因子盲挖流水线协调器，协调字段加载、候选生成、分层抽样、剪枝与回填蒸馏模板等阶段。"""

    def __init__(self, config: CarpetMiningConfig, db: Optional[AlphaDatabase] = None):
        """初始化协调器。

        Args:
            config: 盲挖挖掘配置项。
            db: 目标因子数据库实例。
        """
        self.config = config
        self.db = db or AlphaDatabase()
        self.simulator = BrainPlatformSimulator()
        if config.seed is not None:
            random.seed(config.seed)

    def load_available_fields(self) -> List[Dict[str, object]]:
        """从对应数据集中加载全部可用数据字段。"""
        logger.info("地毯式挖掘 - 开始从可用数据集中加载可用字段列表...")
        result = load_available_fields(self.config)
        logger.info("地毯式挖掘 - 成功加载 %d 个有效字段", len(result))
        return result

    def generate_candidate_expressions_by_category(self, fields: List[Dict[str, object]]) -> Dict[str, List[Task]]:
        """按因子种类分类生成待测试的候选因子 AST 表达式任务。"""
        logger.info("地毯式挖掘 - 开始基于 %d 个可用字段生成候选表达式列表...", len(fields))
        result = generate_candidate_expressions_by_category(self.config, self.db, fields)
        total = sum(len(tasks) for tasks in result.values())
        logger.info("地毯式挖掘 - 候选因子表达式生成完成，共计 %d 个任务分布在 %d 个品类中", total, len(result))
        return result

    def sample_cohort(self, categorized_tasks: Dict[str, List[Task]]) -> List[Task]:
        """对分类的候选任务空间执行分层抽样，控制回测规模与额度。"""
        logger.info("地毯式挖掘 - 正在执行分层抽样，控制回测预算...")
        result = sample_cohort(self.config, self.db, categorized_tasks)
        logger.info("地毯式挖掘 - 采样完毕，生成 %d 个待回测样本的组合队列", len(result))
        return result

    def run_batch_simulation_and_persist(self, cohort: List[Task]) -> List[PlatformAlphaResult]:
        """在平台并发提交回测任务批次并持久化回测结果。"""
        logger.info("地毯式挖掘 - 正在将 %d 个因子的组合队列提交至回测端运行...", len(cohort))
        from alpha_operator_framework.carpet.simulation import run_batch_simulation_and_persist
        result = run_batch_simulation_and_persist(self, cohort)
        logger.info("地毯式挖掘 - 回测数据持久化写库完成")
        return result

    def prune_zero_signal_families(self, cohort: List[Task], results: List[PlatformAlphaResult]) -> List[str]:
        """根据回测结果剔除无信号的因子结构族，优化后续搜索方向。"""
        logger.info("地毯式挖掘 - 正在分析回测指标并剪枝无信号因子结构族...")
        from alpha_operator_framework.carpet.optimization import prune_zero_signal_families
        result = prune_zero_signal_families(self, cohort, results)
        logger.info("地毯式挖掘 - 剪枝完毕，共剔除了 %d 个无信号的结构族: %s", len(result), result)
        return result

    def optimize_positive_signals(self, results: List[PlatformAlphaResult]) -> List[PlatformAlphaResult]:
        """对展现出良好信号潜力的因子执行针对性微调与变异优化。"""
        logger.info("地毯式挖掘 - 正在对表现出信号的优势因子进行深度微调与变异优化...")
        from alpha_operator_framework.carpet.optimization import optimize_positive_signals
        result = optimize_positive_signals(self, results)
        logger.info("地毯式挖掘 - 深度优化完毕，生成 %d 个优化变异因子回测结果", len(result))
        return result

    def distill_and_persist_winning_templates(self, final_reports: List[JudgeReport]) -> List[str]:
        """将最终通过终审评级的优势因子的模板骨架提取并回填至库中。"""
        logger.info("地毯式挖掘 - 正在从终审通过的优势因子中提取并蒸馏模板骨架...")
        from alpha_operator_framework.carpet.distillation import distill_and_persist_winning_templates
        result = distill_and_persist_winning_templates(self, final_reports)
        logger.info("地毯式挖掘 - 模板蒸馏与入库成功，共回填了 %d 个新模板", len(result))
        return result

    def run(self) -> CarpetMiningResult:
        """运行完整地毯式因子盲挖流水线流程。

        Returns:
            CarpetMiningResult: 盲挖流程运行数据与终审评估排名报告结果。
        """
        started_at = time.time()
        logger.info("=== 启动地毯式挖掘流程 (区域: %s / 股票池: %s) ===", self.config.region, self.config.universe)
        fields = self.load_available_fields()
        if not fields:
            logger.error("在所选的区域及数据集配置中未发现任何有效的数据字段，流程中断")
            raise RuntimeError("未在指定数据集中找到有效字段，请检查数据集名称与区域配置")
        
        categorized_tasks = self.generate_candidate_expressions_by_category(fields)
        cohort = self.sample_cohort(categorized_tasks)
        first_gen_results = self.run_batch_simulation_and_persist(cohort)
        pruned_families = self.prune_zero_signal_families(cohort, first_gen_results)
        optimized_results = self.optimize_positive_signals(first_gen_results)
        
        details = [result.raw_details for result in first_gen_results + optimized_results if result.raw_details]
        logger.info("正在将回测表现数据汇聚至 AlphaJudge 进行终审评级...")
        ranked_reports = AlphaJudge().rank_candidates(details) if details else []
        logger.info("AlphaJudge 排名评级生成完毕，共评估了 %d 个通过回测的因子", len(ranked_reports))
        
        distilled_templates = self.distill_and_persist_winning_templates(ranked_reports)
        total_generated = sum(len(tasks) for tasks in categorized_tasks.values())
        all_ids = [result.alpha_id for result in first_gen_results + optimized_results if result.alpha_id and not result.alpha_id.startswith("FAILED_")]
        self._record_backtests(total_generated, len(cohort))
        
        elapsed = time.time() - started_at
        logger.info("=== 地毯式挖掘流程全部执行完毕！总耗时: %.2f 秒 ===", elapsed)
        
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
            elapsed_seconds=elapsed,
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
            except Exception as ex:
                logger.warning("记录回测历史记录时抛出异常: %s", ex)


def _run_stratified_carpet_mining_with(miner_type, region: str = "GBR", universe: str = "TOP700", datasets: Optional[Sequence[str]] = None, sample_per_family: int = 4, batch_size: int = 5, delay: int = 1, decay: int = 12, neutralization: str = "SUBINDUSTRY", truncation: float = 0.08, execute: bool = True, seed: Optional[int] = None, output_report_path: Optional[str] = None) -> CarpetMiningResult:
    config = CarpetMiningConfig(region=region, universe=universe, delay=delay, datasets=list(datasets) if datasets else ["insider_agg_matrix", "pattern_scores", "fundamental31", "risk60"], sample_per_family=sample_per_family, batch_size=batch_size, decay=decay, neutralization=neutralization, truncation=truncation, execute=execute, seed=seed)
    result = miner_type(config).run()
    if output_report_path:
        report_path = Path(output_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(result.summary_markdown(), encoding="utf-8")
        logger.info("已成功导出研报至: %s", report_path)
    return result


def run_stratified_carpet_mining(region: str = "GBR", universe: str = "TOP700", datasets: Optional[Sequence[str]] = None, sample_per_family: int = 4, batch_size: int = 5, delay: int = 1, decay: int = 12, neutralization: str = "SUBINDUSTRY", truncation: float = 0.08, execute: bool = True, seed: Optional[int] = None, output_report_path: Optional[str] = None) -> CarpetMiningResult:
    """提供给外部 API 一键调用地毯式盲挖的首发入口包装函数。"""
    return _run_stratified_carpet_mining_with(StratifiedCarpetMiner, region, universe, datasets, sample_per_family, batch_size, delay, decay, neutralization, truncation, execute, seed, output_report_path)
