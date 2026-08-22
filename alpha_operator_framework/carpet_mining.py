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
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.ast import (
    BreederConfig,
    SymbolicTreeBreeder,
    canonicalize_expression,
    extract_ast_fields,
    parse_expression,
    to_canonical_string,
)
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge, JudgeReport
from alpha_operator_framework.distill.diagnostic import FailureDiagnosis, FailureMode, diagnose_alpha_failure
from alpha_operator_framework.distill.mutation import AlphaMutator
from alpha_operator_framework.distill.template_abstractor import abstract_templates
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
    seed: Optional[int] = None            # 随机种子 (None 时动态随机并结合数据库增量去重)


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
    distilled_templates: List[str] = field(default_factory=list)

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
            f"- **自主蒸馏模板**: 新沉淀 `{len(self.distilled_templates)}` 个高阶模板至知识库",
            f"- **全流程耗时**: `{self.elapsed_seconds:.1f}` 秒",
            f"",
            f"## 一、 综合优胜 Alpha 终审排行榜 (Top 10)",
            f"",
            f"| 排名 | 平台 Alpha ID | 来源类别 | Sharpe | Fitness | 换手率 | 年化收益 | 最大回撤 | 评级 | 行动建议 |",
            f"| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ]

        for idx, rep in enumerate(self.ranked_reports[:10], 1):
            icon = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"{idx}"))
            m = rep.metrics if hasattr(rep, "metrics") and rep.metrics else {}
            if isinstance(m, dict):
                sharpe = float(m.get("sharpe") or 0.0)
                fitness = float(m.get("fitness") or 0.0)
                turnover = float(m.get("turnover") or 0.0)
                returns = float(m.get("returns") or m.get("annualized_return") or 0.0)
                drawdown = float(m.get("drawdown") or m.get("max_drawdown") or 0.0)
            else:
                sharpe = float(getattr(m, "sharpe", 0.0))
                fitness = float(getattr(m, "fitness", 0.0))
                turnover = float(getattr(m, "turnover", 0.0))
                returns = float(getattr(m, "returns", getattr(m, "annualized_return", 0.0)))
                drawdown = float(getattr(m, "drawdown", getattr(m, "max_drawdown", 0.0)))

            family = getattr(rep, "family", None) or (m.get("family") if isinstance(m, dict) else getattr(m, "family", "mining")) or "mining"
            verdict_val = rep.verdict.value if hasattr(rep.verdict, "value") else str(rep.verdict)
            rec = rep.actionable_recommendations[0] if rep.actionable_recommendations else "保持观察"
            lines.append(
                f"| {icon} | `{rep.alpha_id}` | `{family}` | **{sharpe:.2f}** | {fitness:.2f} | {turnover:.1%} | **{returns:.2%}** | {drawdown:.1%} | `{verdict_val}` | {rec} |"
            )

        if self.ranked_reports:
            best = self.ranked_reports[0]
            m = best.metrics if hasattr(best, "metrics") and best.metrics else {}
            if isinstance(m, dict):
                b_sharpe = float(m.get("sharpe") or 0.0)
                b_fitness = float(m.get("fitness") or 0.0)
                b_turnover = float(m.get("turnover") or 0.0)
                b_returns = float(m.get("returns") or m.get("annualized_return") or 0.0)
                b_drawdown = float(m.get("drawdown") or m.get("max_drawdown") or 0.0)
            else:
                b_sharpe = float(getattr(m, "sharpe", 0.0))
                b_fitness = float(getattr(m, "fitness", 0.0))
                b_turnover = float(getattr(m, "turnover", 0.0))
                b_returns = float(getattr(m, "returns", getattr(m, "annualized_return", 0.0)))
                b_drawdown = float(getattr(m, "drawdown", getattr(m, "max_drawdown", 0.0)))
            lines.extend([
                f"",
                f"## 二、 重点优胜 Alpha 详情",
                f"",
                f"- **平台 Alpha ID**: `{best.alpha_id}`",
                f"- **规范 AST 表达式**: `{best.expression}`",
                f"- **综合表现**: Sharpe **{b_sharpe:.2f}**, Fitness **{b_fitness:.2f}**, 年化收益 **{b_returns:.2%}**, 最大回撤 **{b_drawdown:.1%}**, 换手率 **{b_turnover:.1%}**",
            ])

        if self.distilled_templates:
            lines.extend([
                f"",
                f"## 三、 🧬 本轮自主反向蒸馏沉淀的新模板骨架",
                f"",
                f"系统已自动将本轮胜出的高夏普 Alpha 结构泛化提取并存入 `template_library` 数据库，后续将自动跨数据集复用：",
                f"",
            ])
            for idx, skel in enumerate(self.distilled_templates, 1):
                lines.append(f"{idx}. `{skel}`")

        return "\n".join(lines)


def _extract_task_fields(t: Task) -> List[str]:
    """提取 Task 中涉及的全部原子特征字段."""
    if t.meta:
        if "field" in t.meta and isinstance(t.meta["field"], str):
            return [t.meta["field"]]
        if "fields" in t.meta and isinstance(t.meta["fields"], (list, tuple)):
            return list(t.meta["fields"])
    if t.base_fields:
        return list(t.base_fields)
    try:
        fields = extract_ast_fields(t.expression)
        if fields:
            return list(fields)
    except Exception:
        pass
    # Regex fallback
    tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", t.expression)
    exclude = {
        "rank", "group_rank", "group_neutralize", "group_zscore", "group_scale",
        "ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev",
        "subindustry", "industry", "sector", "market", "cap", "winsorize", "ts_backfill",
        "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_stddev", "vec_range", "std"
    }
    return [tok for tok in tokens if tok not in exclude and not tok.isdigit()]


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
            "sector_decomposition": [],  # 6. 行业-特质正交分解与Beta剪刀差
            "three_tier_scaling": [],    # 7. 三层架构: 原始特征 ➔ 截面行业/市值分箱 ➔ 时序尺度标准化
            "cross_interaction": [],      # 8. 多源跨数据集协同
            "evolved_distillation": [],  # 9. 数据库自主进化模板动态回流与实例化
            "symbolic_evolution": [],   # 10. 符号语法树自由杂交与进化探索
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
                    expression=f"group_neutralize(rank(ts_decay_linear({atom}, 10)) - rank(ts_decay_linear({atom}, 30)), {self.config.neutralization.lower()})",
                    decay=10,
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
            for w_delta, w_std in ((10, 20), (20, 40), (60, 120)):
                categorized_tasks["asymmetric_risk"].append(
                    Task(
                        family="asymmetric_risk",
                        template_index=9,
                        fields_per_alpha=1,
                        expression=f"group_neutralize(rank(ts_delta({atom}, {w_delta})) / (0.01 + rank(ts_std_dev({atom}, {w_std}))), {self.config.neutralization.lower()})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window_delta": w_delta, "window_std": w_std},
                    )
                )

        # 6. 行业-特质正交分解族 (sector_decomposition)
        neut_group = self.config.neutralization.lower()
        for fid, atom, ds in atomic_fields:
            for w in (22, 63, 126):
                categorized_tasks["sector_decomposition"].append(
                    Task(
                        family="sector_decomposition",
                        template_index=11,
                        fields_per_alpha=1,
                        expression=f"ts_zscore({atom}, {w}) - ts_zscore(group_neutralize({atom}, {neut_group}), {w})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w, "decomp_type": "beta_drift"},
                    )
                )
                categorized_tasks["sector_decomposition"].append(
                    Task(
                        family="sector_decomposition",
                        template_index=12,
                        fields_per_alpha=1,
                        expression=f"group_neutralize(ts_rank(group_neutralize({atom}, {neut_group}), {w}) - ts_rank({atom}, {w}), {neut_group})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w, "decomp_type": "idiosyncratic_divergence"},
                    )
                )

        # 7. 三层架构: 原始特征 ➔ 截面行业/市值分箱 ➔ 时序尺度标准化 (three_tier_scaling)
        for fid, atom, ds in atomic_fields:
            for w in (22, 66, 120, 240):
                # 变体 1: ts_scale 极值截面标准化
                categorized_tasks["three_tier_scaling"].append(
                    Task(
                        family="three_tier_scaling",
                        template_index=13,
                        fields_per_alpha=1,
                        expression=f"ts_scale(group_rank({atom}, {neut_group}), {w})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w, "tier_type": "ts_scale_industry"},
                    )
                )
                # 变体 2: ts_rank 排序保留
                categorized_tasks["three_tier_scaling"].append(
                    Task(
                        family="three_tier_scaling",
                        template_index=14,
                        fields_per_alpha=1,
                        expression=f"ts_rank(group_rank({atom}, {neut_group}), {w})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w, "tier_type": "ts_rank_industry"},
                    )
                )
                # 变体 3: ts_zscore 高斯标准化
                categorized_tasks["three_tier_scaling"].append(
                    Task(
                        family="three_tier_scaling",
                        template_index=15,
                        fields_per_alpha=1,
                        expression=f"ts_zscore(group_rank({atom}, {neut_group}), {w})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w, "tier_type": "ts_zscore_industry"},
                    )
                )
                # 变体 4: 市值十分箱中性化 + ts_scale
                categorized_tasks["three_tier_scaling"].append(
                    Task(
                        family="three_tier_scaling",
                        template_index=16,
                        fields_per_alpha=1,
                        expression=f"ts_scale(group_rank({atom}, bucket(rank(cap), range='0.1, 1, 0.1')), {w})",
                        decay=self.config.decay,
                        meta={"dataset": ds, "field": fid, "window": w, "tier_type": "ts_scale_market_cap_bucket"},
                    )
                )

        # 8. 多源跨数据集协同族 (cross_interaction)
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

        # 9. 动态从数据库 template_library 加载并实例化自主进化与用户自定义模板
        if self.db and hasattr(self.db, "list_templates"):
            try:
                db_templates = self.db.list_templates(active_only=True)
                for tpl in db_templates:
                    raw_tpl = tpl.expression_template
                    if not raw_tpl or ("{" not in raw_tpl and "<" not in raw_tpl):
                        continue

                    # 1. 递归展开算子元占位符 ({op_ts}, {op_group}, {op_cross} 等)
                    tpl_variants = [raw_tpl]
                    if "{op_ts}" in raw_tpl or "<op_ts>" in raw_tpl:
                        new_vars = []
                        for op in ["ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta"]:
                            for v in tpl_variants:
                                new_vars.append(v.replace("{op_ts}", op).replace("<op_ts>", op))
                        tpl_variants = new_vars

                    if "{op_group}" in raw_tpl or "<op_group>" in raw_tpl:
                        new_vars = []
                        for op in ["group_rank", "group_neutralize", "group_zscore", "group_scale"]:
                            for v in tpl_variants:
                                new_vars.append(v.replace("{op_group}", op).replace("<op_group>", op))
                        tpl_variants = new_vars

                    if "{op_cross}" in raw_tpl or "<op_cross>" in raw_tpl:
                        new_vars = []
                        for op in ["vector_neut", "regression_neut", "ts_corr"]:
                            for v in tpl_variants:
                                new_vars.append(v.replace("{op_cross}", op).replace("<op_cross>", op))
                        tpl_variants = new_vars

                    def _instantiate_params(expr_str: str) -> str:
                        res = expr_str.replace("{group}", neut_group).replace("<group>", neut_group)
                        res = res.replace("{decay}", str(self.config.decay)).replace("<decay>", str(self.config.decay))
                        res = res.replace("{window}", "20").replace("<window>", "20").replace("{w}", "20")
                        res = res.replace("{w1}", "20").replace("{w2}", "40")
                        return res

                    # 2. 遍历展开后的变体并填入特征字段
                    for sub_tpl in tpl_variants:
                        feature_slots = sorted(list(set(re.findall(r"\{([a-d])\}", sub_tpl))))
                        num_slots = len(feature_slots)

                        if num_slots == 1:
                            for fid, atom, ds in atomic_fields:
                                inst_expr = _instantiate_params(sub_tpl.replace("{a}", atom).replace("<a>", atom))
                                categorized_tasks["evolved_distillation"].append(
                                    Task(
                                        family=tpl.family or "evolved_distillation",
                                        template_index=tpl.template_index or 999,
                                        fields_per_alpha=1,
                                        expression=inst_expr,
                                        decay=self.config.decay,
                                        meta={"dataset": ds, "field": fid, "from_db_template": tpl.name},
                                    )
                                )
                        elif num_slots == 2 and len(atomic_fields) >= 2:
                            for i in range(min(len(atomic_fields), 8)):
                                fid1, atom1, ds1 = atomic_fields[i]
                                for j in range(i + 1, min(len(atomic_fields), 10)):
                                    fid2, atom2, ds2 = atomic_fields[j]
                                    inst_expr = _instantiate_params(
                                        sub_tpl.replace("{a}", atom1).replace("<a>", atom1)
                                               .replace("{b}", atom2).replace("<b>", atom2)
                                    )
                                    categorized_tasks["evolved_distillation"].append(
                                        Task(
                                            family=tpl.family or "evolved_distillation",
                                            template_index=tpl.template_index or 999,
                                            fields_per_alpha=2,
                                            expression=inst_expr,
                                            decay=self.config.decay,
                                            meta={"dataset": f"{ds1}+{ds2}", "fields": [fid1, fid2], "from_db_template": tpl.name},
                                        )
                                    )
                        elif num_slots == 3 and len(atomic_fields) >= 3:
                            for i in range(min(len(atomic_fields), 4)):
                                fid1, atom1, ds1 = atomic_fields[i]
                                for j in range(i + 1, min(len(atomic_fields), 5)):
                                    fid2, atom2, ds2 = atomic_fields[j]
                                    for k_idx in range(j + 1, min(len(atomic_fields), 6)):
                                        fid3, atom3, ds3 = atomic_fields[k_idx]
                                        inst_expr = _instantiate_params(
                                            sub_tpl.replace("{a}", atom1).replace("<a>", atom1)
                                                   .replace("{b}", atom2).replace("<b>", atom2)
                                                   .replace("{c}", atom3).replace("<c>", atom3)
                                        )
                                        categorized_tasks["evolved_distillation"].append(
                                            Task(
                                                family=tpl.family or "evolved_distillation",
                                                template_index=tpl.template_index or 999,
                                                fields_per_alpha=3,
                                                expression=inst_expr,
                                                decay=self.config.decay,
                                                meta={"dataset": f"{ds1}+{ds2}+{ds3}", "fields": [fid1, fid2, fid3], "from_db_template": tpl.name},
                                            )
                                        )
                        elif num_slots == 4 and len(atomic_fields) >= 4:
                            fid1, atom1, _ = atomic_fields[0]
                            fid2, atom2, _ = atomic_fields[1]
                            fid3, atom3, _ = atomic_fields[2]
                            fid4, atom4, _ = atomic_fields[3]
                            inst_expr = _instantiate_params(
                                sub_tpl.replace("{a}", atom1).replace("<a>", atom1)
                                       .replace("{b}", atom2).replace("<b>", atom2)
                                       .replace("{c}", atom3).replace("<c>", atom3)
                                       .replace("{d}", atom4).replace("<d>", atom4)
                            )
                            categorized_tasks["evolved_distillation"].append(
                                Task(
                                    family=tpl.family or "evolved_distillation",
                                    template_index=tpl.template_index or 999,
                                    fields_per_alpha=4,
                                    expression=inst_expr,
                                    decay=self.config.decay,
                                    meta={"dataset": "multi_dataset", "fields": [fid1, fid2, fid3, fid4], "from_db_template": tpl.name},
                                )
                            )
            except Exception as e:
                logger.debug(f"加载 DB 进化模板库跳过: {e}")

        # 10. 符号语法树自由杂交引擎自主进化生成 (无需预置模板)
        try:
            breeder = SymbolicTreeBreeder(BreederConfig(seed=self.config.seed))
            symbolic_tasks = breeder.breed_task_cohort(
                fields=fields,
                default_decay=self.config.decay,
                neutralization=self.config.neutralization,
            )
            categorized_tasks["symbolic_evolution"] = symbolic_tasks
        except Exception as e:
            logger.warning(f"符号语法树杂交引擎执行异常: {e}")

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
        """从各个表达式类别中进行【字段-算子双轴均衡正交抽样】(保障字段全覆盖 + 算子均衡 + 未测空间优先)."""
        import hashlib
        from collections import defaultdict
        cohort: List[Task] = []
        k = self.config.sample_per_family

        # 1. 查找数据库中已回测过的表达式 SHA
        existing_shas: set[str] = set()
        if self.db:
            try:
                conn = self.db._get_connection()
                rows = conn.execute(
                    "SELECT expression_sha FROM alpha_expressions WHERE status IN ('completed', 'failed', 'pruned')"
                ).fetchall()
                existing_shas = {r[0] for r in rows}
            except Exception:
                pass

        rng = random.Random(self.config.seed) if self.config.seed is not None else random

        # 2. 统计当前候选池中涉及的所有唯一字段，用于全局覆盖度跟踪与轮转保底
        all_unique_fields: set[str] = set()
        for cat, task_list in categorized_tasks.items():
            for t in task_list:
                for f in _extract_task_fields(t):
                    all_unique_fields.add(f)

        unique_fields_list = sorted(list(all_unique_fields))
        # 全局字段采样频次计数器 (确保每个字段得到公平回测机会，防止字段饥饿)
        field_sampled_counts: Dict[str, int] = defaultdict(int)

        # 3. 逐分类进行【字段-算子双轴正交分层抽样】
        for cat, task_list in categorized_tasks.items():
            if not task_list:
                continue

            # 区分已回测与未回测候选，并按主字段分桶
            untested_by_field: Dict[str, List[Task]] = defaultdict(list)
            tested_by_field: Dict[str, List[Task]] = defaultdict(list)
            all_untested: List[Task] = []
            all_tested: List[Task] = []

            for t in task_list:
                t_sha = self.db.compute_sha(t.expression) if self.db else hashlib.sha256(t.expression.strip().encode()).hexdigest()
                t_fields = _extract_task_fields(t)
                primary_f = t_fields[0] if t_fields else "unknown"

                if t_sha in existing_shas:
                    tested_by_field[primary_f].append(t)
                    all_tested.append(t)
                else:
                    untested_by_field[primary_f].append(t)
                    all_untested.append(t)

            cat_sampled: List[Task] = []

            # ------------------------------------------------------------------
            # Phase A: 字段公平轮转保底 (Field-Fairness Round-Robin)
            # 优先从各字段的未测候选 (untested) 中按全局采样频次升序抽取
            # ------------------------------------------------------------------
            # 字段排序准则: 优先全局被抽样次数最少的字段 (防饥饿) + 打乱同频次字段
            sorted_fields = sorted(
                unique_fields_list,
                key=lambda f: (field_sampled_counts[f], rng.random())
            )

            # 第一轮：为最饥饿的字段各分配 1 条该算子族的未测表达式
            for f in sorted_fields:
                if len(cat_sampled) >= k:
                    break
                if untested_by_field[f]:
                    # 从该字段的未测候选中随机选 1 条
                    chosen_task = rng.choice(untested_by_field[f])
                    cat_sampled.append(chosen_task)
                    untested_by_field[f].remove(chosen_task)
                    if chosen_task in all_untested:
                        all_untested.remove(chosen_task)
                    for tf in _extract_task_fields(chosen_task):
                        field_sampled_counts[tf] += 1

            # ------------------------------------------------------------------
            # Phase B: 族群剩余配额未测空间补充 (Quota Top-up from Untested)
            # ------------------------------------------------------------------
            if len(cat_sampled) < k and all_untested:
                needed = k - len(cat_sampled)
                rng.shuffle(all_untested)
                top_up = all_untested[:needed]
                for chosen_task in top_up:
                    cat_sampled.append(chosen_task)
                    for tf in _extract_task_fields(chosen_task):
                        field_sampled_counts[tf] += 1

            # ------------------------------------------------------------------
            # Phase C: 未测空间耗尽时的历史回测条目回退 (Tested Fallback)
            # ------------------------------------------------------------------
            if len(cat_sampled) < k:
                needed = k - len(cat_sampled)
                if all_tested:
                    rng.shuffle(all_tested)
                    top_up_tested = all_tested[:min(needed, len(all_tested))]
                    for chosen_task in top_up_tested:
                        cat_sampled.append(chosen_task)
                        for tf in _extract_task_fields(chosen_task):
                            field_sampled_counts[tf] += 1
                    logger.info(f"[{cat}] 未回测候选不足，已补充 {len(top_up_tested)} 条历史条目")

            cohort.extend(cat_sampled)

        # 4. 计算并输出双轴覆盖度指标
        covered_fields = {f for f, cnt in field_sampled_counts.items() if cnt > 0 and f in all_unique_fields}
        coverage_pct = (len(covered_fields) / len(all_unique_fields) * 100.0) if all_unique_fields else 100.0
        
        logger.info(
            f"🎯 【双轴正交分层抽样完成】:\n"
            f"   • 字段覆盖度: 覆盖了 {len(covered_fields)}/{len(all_unique_fields)} 个原子特征 (覆盖率: {coverage_pct:.1f}%)\n"
            f"   • 族群均衡度: 10 大算子族共抽样 {len(cohort)} 条任务\n"
            f"   • 平均每字段测试频次: {sum(field_sampled_counts.values()) / max(1, len(covered_fields)):.1f} 次"
        )
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
        """【二维解耦智能剪枝】: 结合多字段共识与金牌豁免机制，淘汰真正失效的结构模式 (杜绝误杀与漏判)."""
        from alpha_operator_framework.distill.template_pruner import (
            evaluate_and_prune_templates_2d,
            analyze_field_signal_quality,
        )

        # 1. 执行二维多字段共识剪枝
        prune_res = evaluate_and_prune_templates_2d(
            db=self.db,
            results=results,
            min_distinct_fields=2,
            failure_rate_threshold=0.80,
            max_avg_sharpe=0.10,
            min_sample_n=3,
        )

        for log in prune_res.audit_logs:
            logger.info(log)

        # 2. 评估字段级信号画像 (噪声字段 vs Alpha 字段)
        field_profiles = analyze_field_signal_quality(results)
        noise_fields = [f for f, p in field_profiles.items() if p.is_noise]
        alpha_fields = [f for f, p in field_profiles.items() if p.tier == "Alpha"]
        if noise_fields:
            logger.info(f"⚠️ [字段画像] 识别到 {len(noise_fields)} 个跨族纯白噪声字段 (暂不误杀对应模板): {noise_fields}")
        if alpha_fields:
            logger.info(f"✨ [字段画像] 识别到 {len(alpha_fields)} 个高信噪比 Alpha 特征: {alpha_fields}")

        return prune_res.pruned_patterns

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

    def distill_and_persist_winning_templates(
        self,
        final_reports: List[JudgeReport],
    ) -> List[str]:
        """从回测终审胜出的高分 Alpha 中反向抽象骨架，并自动沉淀至 template_library 知识库."""
        winning_exprs: List[str] = []
        for rep in final_reports:
            m = rep.metrics if hasattr(rep, "metrics") and rep.metrics else {}
            sharpe = float(m.get("sharpe") or (getattr(m, "sharpe", 0.0) if hasattr(m, "sharpe") else 0.0) or 0.0)
            verdict_str = str(rep.verdict.value if hasattr(rep.verdict, "value") else rep.verdict)
            if sharpe >= 1.0 or rep.priority_score >= 60.0 or verdict_str == "ACCEPTED":
                if rep.expression and rep.expression not in winning_exprs:
                    winning_exprs.append(rep.expression)

        if not winning_exprs:
            logger.info("本轮未发现达到蒸馏门槛 (Sharpe>=1.0) 的胜出 Alpha，跳过模板抽象")
            return []

        # 执行反向语法骨架抽象
        abstractions = abstract_templates(winning_exprs, min_support=1)
        distilled_skeletons: List[str] = []

        if self.db and hasattr(self.db, "save_abstracted_template"):
            for abs_tpl in abstractions:
                saved = self.db.save_abstracted_template(
                    expression_template=abs_tpl.expression_template,
                    family="evolved_distillation",
                    title="自主进化高阶模板",
                    description=f"由地毯式挖掘胜出因子自动蒸馏生成 (支撑度: {abs_tpl.support})",
                    support_count=abs_tpl.support,
                    source="autonomous_distillation",
                    example_expression=abs_tpl.source_expressions[0] if abs_tpl.source_expressions else "",
                )
                if saved:
                    distilled_skeletons.append(abs_tpl.expression_template)

        if distilled_skeletons:
            print(f"\n✨ [知识沉淀] 成功从本轮胜出因子中自主反向蒸馏出 {len(distilled_skeletons)} 个高阶模板并写入知识库:")
            for idx, skel in enumerate(distilled_skeletons[:5], 1):
                print(f"   {idx}. `{skel}`")

        return distilled_skeletons

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

        # 8. ★ 自动反向抽象蒸馏与知识库沉淀
        distilled_templates = self.distill_and_persist_winning_templates(final_reports)

        all_ids = [r.alpha_id for r in (first_gen_results + opt_results) if r.alpha_id and not r.alpha_id.startswith("FAILED_")]
        elapsed = time.time() - start_time

        # 记录已回测数据集
        if self.db and hasattr(self.db, "upsert_backtest_record"):
            for ds in self.config.datasets:
                try:
                    self.db.upsert_backtest_record(
                        region=self.config.region,
                        universe=self.config.universe,
                        delay=self.config.delay,
                        dataset_id=ds,
                        strategy="carpet_mining",
                        expression_count=total_gen,
                        backtest_count=len(cohort),
                    )
                except Exception:
                    pass

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
            distilled_templates=distilled_templates,
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
    seed: Optional[int] = None,
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
        seed=seed,
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
