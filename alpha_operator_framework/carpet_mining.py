"""分层地毯式 Alpha 挖掘与正向自优化引擎 (Stratified Carpet Miner).

核心全流程:
  1. 字段加载与预处理: 从指定数据集列表动态提取并原子化包装字段
  2. 海量表达式生成: 覆盖时序动量、均值回归、差分加速、相对比率、不对称风险等多模板族
  3. 表达式智能分类与分层抽样: 按表达式结构/语义分类，每类随机抽选 N 条代表
  4. 分批并发回测与即时落库: 批次回测，每批完成立刻保存 alpha_expressions, alpha_details, alpha_checks
  5. 智能剪枝: 评估模板族密度，对零信号/违规模式自动生成剪枝规则写库
  6. 信号诊断与针对性自优化: 对产生正向信号的因子自动触发 AST 突变优化 (降换手/调参数/反转)，提交二代优化回测
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.ast import (
    canonicalize_expression,
    extract_ast_fields,
    parse_expression,
    to_canonical_string,
)
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge, JudgeReport
from alpha_operator_framework.distill.diagnostic import FailureDiagnosis, FailureMode, diagnose_alpha_failure
from alpha_operator_framework.distill.mutation import AlphaMutator
from alpha_operator_framework.distill.template_pruner import matches_prune_rule
from alpha_operator_framework.research.field_loader import load_real_market_fields
from alpha_operator_framework.platform.platform_simulator import (
    BrainPlatformSimulator,
    PlatformAlphaResult,
)
from alpha_operator_framework.research.db_persister import persist_research_pipeline_results

logger = logging.getLogger(__name__)


@dataclass
class CarpetMiningConfig:
    """地毯式挖掘配置."""

    region: str = "GBR"
    universe: str = "TOP700"
    delay: int = 1
    datasets: List[str] = field(default_factory=list)
    sample_per_family: int = 4            # 每一类表达式随机抽取的候选数量
    batch_size: int = 5                   # 平台回测每批任务数
    decay: int = 12                       # 默认 decay 周期
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    unit_handling: str = "VERIFY"
    nan_handling: str = "OFF"
    optimize_signals: bool = True         # 是否对正向信号自动执行二代优化
    min_sharpe_for_opt: float = 0.35      # 触发自优化的最低 Sharpe 门槛
    min_return_for_opt: float = 0.02      # 触发自优化的最低年化收益率门槛 (2%)
    execute: bool = True                  # 是否真实提交平台模拟
    seed: Optional[int] = 42


@dataclass
class CarpetMiningResult:
    """地毯式挖掘全流程汇总结果."""

    config: CarpetMiningConfig
    total_expressions_generated: int
    sampled_cohort_size: int
    categories_tested: List[str]
    first_gen_results: List[PlatformAlphaResult]
    pruned_families: List[str]
    optimized_results: List[PlatformAlphaResult]
    all_persisted_ids: List[str]
    ranked_reports: List[JudgeReport]
    elapsed_seconds: float

    def summary_markdown(self) -> str:
        """生成 Markdown 格式的执行总结研报."""
        lines = [
            f"# 🎯 地毯式 Alpha 分层挖掘与自进化研报",
            f"",
            f"- **目标市场**: `{self.config.region}` ({self.config.universe}, Delay {self.config.delay})",
            f"- **覆盖数据集**: `{', '.join(self.config.datasets)}`",
            f"- **表达式生成规模**: 初始生成 `{self.total_expressions_generated}` 条 ➔ 分层抽样 `{self.sampled_cohort_size}` 条 ({len(self.categories_tested)} 个大类)",
            f"- **回测与入库**: 平台实测 `{len(self.first_gen_results)}` 条第一代 + `{len(self.optimized_results)}` 条二代优化",
            f"- **淘汰剪枝族数**: `{len(self.pruned_families)}` 族 (已沉淀剪枝规则)",
            f"- **全流程耗时**: `{self.elapsed_seconds:.1f}` 秒",
            f"",
            f"## 一、 综合优胜 Alpha 终审排行榜 (Top 10)",
            f"",
            f"| 排名 | 平台 Alpha ID | 来源类别 | Sharpe | Fitness | 换手率 | 年化收益 | 最大回撤 | 评级 | 行动建议 |",
            f"| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ]

        for idx, rep in enumerate(self.ranked_reports[:10], 1):
            icon = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"{idx}"))
            m = rep.metrics
            rec = rep.actionable_recommendations[0] if rep.actionable_recommendations else "保持观察"
            lines.append(
                f"| {icon} | `{rep.alpha_id}` | `{rep.family or 'mining'}` | **{m.sharpe:.2f}** | {m.fitness:.2f} | {m.turnover:.1%} | **{m.annualized_return:.2%}** | {m.max_drawdown:.1%} | `{rep.verdict.value}` | {rec} |"
            )

        if self.ranked_reports:
            best = self.ranked_reports[0]
            lines.extend([
                f"",
                f"## 二、 重点优胜 Alpha 详情",
                f"",
                f"- **平台 Alpha ID**: `{best.alpha_id}`",
                f"- **规范 AST 表达式**: `{best.expression}`",
                f"- **综合表现**: Sharpe **{best.metrics.sharpe:.2f}**, 年化收益 **{best.metrics.annualized_return:.2%}**, 最大回撤 **{best.metrics.max_drawdown:.1%}**, 换手率 **{best.metrics.turnover:.1%}**",
            ])

        return "\n".join(lines)


class StratifiedCarpetMiner:
    """分层地毯式 Alpha 挖掘器."""

    def __init__(self, config: CarpetMiningConfig, db: Optional[AlphaDatabase] = None):
        self.config = config
        self.db = db or AlphaDatabase()
        self.simulator = BrainPlatformSimulator()
        if self.config.seed is not None:
            random.seed(self.config.seed)

    def load_available_fields(self) -> List[Dict[str, Any]]:
        """从指定的数据集列表中提取有效字段."""
        specs = load_real_market_fields(
            region=self.config.region,
            universe=self.config.universe,
            delay=self.config.delay,
            datasets=self.config.datasets,
            max_fields=300,
        )
        all_fields = [
            {
                "id": s.id,
                "dataset_id": s.dataset_id,
                "type": s.type,
                "coverage": s.coverage,
                "description": s.description,
            }
            for s in specs
            if s.id.lower() not in ("close", "open", "high", "low", "vwap", "sharesout", "market_cap")
        ]
        logger.info(f"成功加载 {len(all_fields)} 个候选字段 (来自数据集: {', '.join(self.config.datasets)})")
        return all_fields

    def generate_candidate_expressions_by_category(
        self,
        fields: List[Dict[str, Any]],
    ) -> Dict[str, List[Task]]:
        """海量生成多阶 AST 表达式，并按语义/结构模板族严格分类."""
        categorized_tasks: Dict[str, List[Task]] = {
            "ts_momentum": [],           # 1. 时序动量与趋势持续
            "mean_reversion": [],         # 2. 均值回归与超买超卖反转
            "macd_velocity": [],          # 3. 长短均线加速度 (MACD)
            "relative_ratio": [],         # 4. 截面相对比率与估值溢价
            "asymmetric_risk": [],        # 5. 波动率与下行风险不对称惩罚
            "cross_interaction": [],      # 6. 多源跨数据集协同
        }

        # 准备原子包装字段
        atomic_fields = []
        for f in fields:
            fid = f["id"]
            ftype = f.get("type", "MATRIX")
            if ftype in ("VECTOR", "EVENT"):
                atomic = f"winsorize(ts_backfill(vec_avg({fid}), 120), std=4.0)"
            elif "rank" in fid or "score" in fid:
                atomic = f"rank({fid})"
            else:
                atomic = fid
            atomic_fields.append((fid, atomic, f.get("dataset_id", "")))

        if not atomic_fields:
            return categorized_tasks

        # 1. 时序动量族 (ts_momentum)
        for fid, atom, ds in atomic_fields:
            for w in (20, 60, 120):
                categorized_tasks["ts_momentum"].append(
                    Task(
                        family="ts_momentum",
                        template_index=1,
                        fields_per_alpha=1,
                        expression=f"group_neutralize(rank(ts_delta({atom}, {w})), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w},
                    )
                )
                categorized_tasks["ts_momentum"].append(
                    Task(
                        family="ts_momentum",
                        template_index=2,
                        fields_per_alpha=1,
                        expression=f"group_neutralize(ts_decay_linear(ts_rank({atom}, {w}), 10), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w},
                    )
                )

        # 2. 均值回归族 (mean_reversion)
        for fid, atom, ds in atomic_fields:
            for w in (10, 22):
                categorized_tasks["mean_reversion"].append(
                    Task(
                        family="mean_reversion",
                        template_index=3,
                        fields_per_alpha=1,
                        expression=f"-1.0 * group_neutralize(rank(ts_delta({atom}, {w})), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w},
                    )
                )
                categorized_tasks["mean_reversion"].append(
                    Task(
                        family="mean_reversion",
                        template_index=4,
                        fields_per_alpha=1,
                        expression=f"-1.0 * group_neutralize(ts_rank({atom}, {w}) - ts_rank({atom}, {w * 3}), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w},
                    )
                )

        # 3. MACD 加速度族 (macd_velocity)
        for fid, atom, ds in atomic_fields:
            categorized_tasks["macd_velocity"].append(
                Task(
                    family="macd_velocity",
                    template_index=5,
                    fields_per_alpha=1,
                    expression=f"group_neutralize(rank(ts_mean({atom}, 20) - ts_mean({atom}, 120)), {self.config.neutralization.lower()})",
                    decay=15,
                    meta={"dataset": ds, "field": fid},
                )
            )
            categorized_tasks["macd_velocity"].append(
                Task(
                    family="macd_velocity",
                    template_index=6,
                    fields_per_alpha=1,
                    expression=f"group_neutralize(rank(ts_decay_linear({atom}, 30)) - rank(ts_decay_linear({atom}, 90)), {self.config.neutralization.lower()})",
                    decay=20,
                    meta={"dataset": ds, "field": fid},
                )
            )

        # 4. 相对比率族 (relative_ratio)
        for i in range(len(atomic_fields)):
            fid1, atom1, ds1 = atomic_fields[i]
            for j in range(i + 1, min(i + 4, len(atomic_fields))):
                fid2, atom2, ds2 = atomic_fields[j]
                categorized_tasks["relative_ratio"].append(
                    Task(
                        family="relative_ratio",
                        template_index=7,
                        fields_per_alpha=2,
                        expression=f"group_neutralize(rank({atom1}) - rank({atom2}), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": f"{ds1}+{ds2}", "fields": [fid1, fid2]},
                    )
                )
                categorized_tasks["relative_ratio"].append(
                    Task(
                        family="relative_ratio",
                        template_index=8,
                        fields_per_alpha=2,
                        expression=f"group_neutralize(rank({atom1}) / (0.01 + rank({atom2})), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": f"{ds1}+{ds2}", "fields": [fid1, fid2]},
                    )
                )

        # 5. 不对称风险惩罚族 (asymmetric_risk)
        for fid, atom, ds in atomic_fields:
            categorized_tasks["asymmetric_risk"].append(
                Task(
                    family="asymmetric_risk",
                    template_index=9,
                    fields_per_alpha=1,
                    expression=f"group_neutralize(rank(ts_delta({atom}, 20)) / (0.01 + rank(ts_std_dev({atom}, 40))), {self.config.neutralization.lower()})",
                    decay=self.config.decay,
                    meta={"dataset": ds, "field": fid},
                )
            )

        # 6. 多源跨数据集协同族 (cross_interaction)
        by_dataset: Dict[str, List[Tuple[str, str]]] = {}
        for fid, atom, ds in atomic_fields:
            by_dataset.setdefault(ds, []).append((fid, atom))

        ds_keys = list(by_dataset.keys())
        if len(ds_keys) >= 2:
            for i in range(len(ds_keys)):
                for j in range(i + 1, len(ds_keys)):
                    ds1, ds2 = ds_keys[i], ds_keys[j]
                    f1_list = by_dataset[ds1]
                    f2_list = by_dataset[ds2]
                    for fid1, atom1 in f1_list[:3]:
                        for fid2, atom2 in f2_list[:3]:
                            categorized_tasks["cross_interaction"].append(
                                Task(
                                    family="cross_interaction",
                                    template_index=10,
                                    fields_per_alpha=2,
                                    expression=f"group_neutralize(rank(ts_decay_linear({atom1}, 20)) * rank({atom2}), {self.config.neutralization.lower()})",
                                    decay=15,
                                    meta={"dataset": f"{ds1}*{ds2}", "fields": [fid1, fid2]},
                                )
                            )

        # 过滤命中现有剪枝规则的表达式
        prune_rules = self.db.get_active_prune_rules() if hasattr(self.db, "get_active_prune_rules") else []
        for cat in categorized_tasks:
            filtered = []
            for t in categorized_tasks[cat]:
                if not any(matches_prune_rule(t.expression, r) for r in prune_rules):
                    filtered.append(t)
            categorized_tasks[cat] = filtered

        total_gen = sum(len(v) for v in categorized_tasks.values())
        logger.info(f"共生成 {total_gen} 条候选表达式，分布在 {len(categorized_tasks)} 个大类中")
        return categorized_tasks

    def sample_cohort(
        self,
        categorized_tasks: Dict[str, List[Task]],
    ) -> List[Task]:
        """从各个表达式类别中进行分层随机抽样 (Stratified Sampling)."""
        cohort: List[Task] = []
        k = self.config.sample_per_family

        for cat, task_list in categorized_tasks.items():
            if not task_list:
                continue
            sampled = random.sample(task_list, min(k, len(task_list)))
            cohort.extend(sampled)

        logger.info(f"分层抽样完成: 从 {len(categorized_tasks)} 类中抽样出 {len(cohort)} 条代表性 Alpha 任务")
        return cohort

    def run_batch_simulation_and_persist(
        self,
        cohort: List[Task],
    ) -> List[PlatformAlphaResult]:
        """分批推进平台回测，并实现每一批结束即时流式持久化入库."""
        if not self.config.execute:
            logger.info("当前为 Dry-Run 模式，跳过真实平台提交")
            return []

        settings = {
            "region": self.config.region,
            "universe": self.config.universe,
            "delay": self.config.delay,
            "decay": self.config.decay,
            "neutralization": self.config.neutralization,
            "truncation": self.config.truncation,
            "unitHandling": self.config.unit_handling,
            "nanHandling": self.config.nan_handling,
        }

        all_results: List[PlatformAlphaResult] = []
        batch_size = self.config.batch_size
        total_batches = (len(cohort) + batch_size - 1) // batch_size

        logger.info(f"开始执行真实平台分批回测: 共 {len(cohort)} 个任务，切分为 {total_batches} 批...")

        for b_idx in range(total_batches):
            chunk = cohort[b_idx * batch_size : (b_idx + 1) * batch_size]
            print(f"\n🚀 [批次 {b_idx + 1}/{total_batches}] 正在提交 {len(chunk)} 个 Alpha 到 WorldQuant BRAIN...")

            # 1. 提交与轮询本批次
            batch_results = self.simulator.simulate_batch(
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
            ds_names = ",".join(self.config.datasets)
            stats = persist_research_pipeline_results(
                db=self.db,
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

    def prune_zero_signal_families(
        self,
        cohort: List[Task],
        results: List[PlatformAlphaResult],
    ) -> List[str]:
        """评估模板族密度，对全部失败/零信号的模板族自动生成剪枝规则写库."""
        pruned: List[str] = []
        family_scores: Dict[str, List[float]] = {}

        for task, res in zip(cohort, results):
            fam = task.family or "general"
            sh = res.sharpe if res.is_valid else -1.0
            family_scores.setdefault(fam, []).append(sh)

        for fam, sharpes in family_scores.items():
            max_sh = max(sharpes) if sharpes else -1.0
            avg_sh = sum(sharpes) / len(sharpes) if sharpes else -1.0
            if max_sh <= 0.0 and avg_sh <= -0.2:
                pruned.append(fam)
                logger.info(f"🚫 剪枝淘汰模板族 {fam}: 样本数 {len(sharpes)}, 最高 Sharpe {max_sh:.2f}, 平均 {avg_sh:.2f}")
                # 记录淘汰规则入库
                try:
                    if hasattr(self.db, "insert_template_prune_rule"):
                        self.db.insert_template_prune_rule(
                            pattern=f"family:{fam}",
                            pattern_type="prefix",
                            family=fam,
                            reason=f"地毯式挖掘零信号淘汰 (max_sharpe={max_sh:.2f})",
                        )
                except Exception as e:
                    logger.warning(f"写入剪枝规则失败: {e}")

        return pruned

    def optimize_positive_signals(
        self,
        results: List[PlatformAlphaResult],
    ) -> List[PlatformAlphaResult]:
        """针对产生正向潜力的 Alpha 自动执行 AST 变异优化与二次实测."""
        if not self.config.optimize_signals or not self.config.execute:
            return []

        candidates_to_opt = [
            r for r in results
            if r.is_valid and (r.sharpe >= self.config.min_sharpe_for_opt or r.annualized_return >= self.config.min_return_for_opt)
        ]

        if not candidates_to_opt:
            logger.info("未发现达到自优化门槛的正向 Alpha，跳过二代变异")
            return []

        print(f"\n🧬 发现 {len(candidates_to_opt)} 个正向 Alpha，开始触发针对性 AST 基因突变与自优化...")

        mutation_tasks: List[Task] = []
        for parent in candidates_to_opt:
            # 1. 诊断病因
            diag = diagnose_alpha_failure({
                "sharpe": parent.sharpe,
                "fitness": parent.fitness,
                "turnover": parent.turnover,
                "returns": parent.annualized_return,
                "drawdown": parent.max_drawdown,
            })

            # 2. 针对高换手率突变
            if parent.turnover > 0.70:
                mutated_exprs = AlphaMutator.mutate_expression(parent.expression, FailureMode.HIGH_TURNOVER)
                for m_idx, m_expr in enumerate(mutated_exprs[:2]):
                    mutation_tasks.append(
                        Task(
                            family="optimized_smooth",
                            template_index=100 + m_idx,
                            fields_per_alpha=1,
                            expression=m_expr,
                            decay=20,  # 提升 decay 周期压降换手率
                            meta={"parent_alpha_id": parent.alpha_id, "opt_type": "turnover_compression"},
                        )
                    )

            # 3. 针对边际 Sharpe 提纯
            if 0.3 <= parent.sharpe < 1.25:
                mutated_exprs = AlphaMutator.mutate_expression(parent.expression, FailureMode.MARGINAL_SHARPE)
                for m_idx, m_expr in enumerate(mutated_exprs[:2]):
                    mutation_tasks.append(
                        Task(
                            family="optimized_sharpe",
                            template_index=200 + m_idx,
                            fields_per_alpha=1,
                            expression=m_expr,
                            decay=parent.raw_details.get("settings", {}).get("decay", self.config.decay),
                            meta={"parent_alpha_id": parent.alpha_id, "opt_type": "sharpe_enhancement"},
                        )
                    )

        if not mutation_tasks:
            return []

        print(f"🚀 正在提交 {len(mutation_tasks)} 个二代变异优化任务到 BRAIN 平台...")
        opt_results = self.simulator.simulate_batch(
            tasks=mutation_tasks,
            settings={
                "region": self.config.region,
                "universe": self.config.universe,
                "delay": self.config.delay,
                "decay": self.config.decay,
                "neutralization": self.config.neutralization,
                "truncation": self.config.truncation,
            },
            poll_interval=4.0,
            timeout=300.0,
        )

        # 实时落库二代优化因子
        valid_details = [r.raw_details for r in opt_results if r.raw_details]
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

        persist_research_pipeline_results(
            db=self.db,
            paper_title=f"GBR Signal Optimization ({','.join(self.config.datasets)})",
            tasks=mutation_tasks,
            settings={"region": self.config.region, "universe": self.config.universe, "delay": self.config.delay},
            platform_results=opt_results,
            ranked_candidates=ranked_cands,
            source_type="evolution",
        )

        return opt_results

    def run(self) -> CarpetMiningResult:
        """执行完整的一键分层地毯式挖掘全流程."""
        start_time = time.time()
        logger.info(f"=== 启动地毯式挖掘流程 ({self.config.region} / {self.config.universe}) ===")

        # 1. 字段提取
        fields = self.load_available_fields()
        if not fields:
            raise RuntimeError("未在指定数据集中找到有效字段，请检查数据集名称与区域配置")

        # 2. 海量表达式生成
        categorized_tasks = self.generate_candidate_expressions_by_category(fields)
        total_gen = sum(len(v) for v in categorized_tasks.values())

        # 3. 表达式分类与分层抽样
        cohort = self.sample_cohort(categorized_tasks)

        # 4. 分批回测与实时流式落库
        first_gen_results = self.run_batch_simulation_and_persist(cohort)

        # 5. 智能剪枝
        pruned_families = self.prune_zero_signal_families(cohort, first_gen_results)

        # 6. 正信号诊断与二次自优化
        opt_results = self.optimize_positive_signals(first_gen_results)

        # 7. 全量结果终审排名
        all_details = [r.raw_details for r in (first_gen_results + opt_results) if r.raw_details]
        judge = AlphaJudge()
        final_reports = judge.rank_candidates(all_details) if all_details else []

        all_ids = [r.alpha_id for r in (first_gen_results + opt_results) if r.alpha_id and not r.alpha_id.startswith("FAILED_")]
        elapsed = time.time() - start_time

        return CarpetMiningResult(
            config=self.config,
            total_expressions_generated=total_gen,
            sampled_cohort_size=len(cohort),
            categories_tested=list(categorized_tasks.keys()),
            first_gen_results=first_gen_results,
            pruned_families=pruned_families,
            optimized_results=opt_results,
            all_persisted_ids=all_ids,
            ranked_reports=final_reports,
            elapsed_seconds=elapsed,
        )


def run_stratified_carpet_mining(
    region: str = "GBR",
    universe: str = "TOP700",
    datasets: Optional[Sequence[str]] = None,
    sample_per_family: int = 4,
    batch_size: int = 5,
    delay: int = 1,
    decay: int = 12,
    neutralization: str = "SUBINDUSTRY",
    truncation: float = 0.08,
    execute: bool = True,
    output_report_path: Optional[str] = None,
) -> CarpetMiningResult:
    """高阶统一入口: 一键执行分层地毯式挖掘、流式落库、剪枝与正向自优化."""
    ds_list = list(datasets) if datasets else ["insider_agg_matrix", "pattern_scores", "fundamental31", "risk60"]
    config = CarpetMiningConfig(
        region=region,
        universe=universe,
        delay=delay,
        datasets=ds_list,
        sample_per_family=sample_per_family,
        batch_size=batch_size,
        decay=decay,
        neutralization=neutralization,
        truncation=truncation,
        execute=execute,
    )

    miner = StratifiedCarpetMiner(config)
    result = miner.run()

    # 导出研报
    if output_report_path:
        out_p = Path(output_report_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(result.summary_markdown(), encoding="utf-8")
        logger.info(f"已导出研报到: {out_p}")

    return result
