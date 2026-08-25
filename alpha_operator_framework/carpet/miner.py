"""分层地毯式 Alpha 挖掘协调器 (Stratified Carpet Miner).

核心全流程:
  1. 字段加载与预处理: 从指定数据集列表动态提取并原子化包装字段
  2. 海量表达式生成: 覆盖时序动量、均值回归、差分加速、相对比率、不对称风险等多模板族
  3. 表达式智能分类与分层抽样: 按表达式结构/语义分类，每类随机抽选 N 条代表
  4. 分批并发回测与即时落库: 批次回测，每批完成立刻保存 alpha_expressions, alpha_details, alpha_checks
  5. 智能剪枝: 评估模板族密度，对零信号/违规模式自动生成剪枝规则写库
  6. 信号诊断与针对性自优化: 对产生正向信号的因子自动触发 AST 突变优化 (降换手/调参数/反转)，提交二代优化回测
"""

from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from alpha_operator_framework.carpet.models import CarpetMiningConfig, CarpetMiningResult
from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.ast import (
    BreederConfig,
    SymbolicTreeBreeder,
    extract_ast_fields,
)
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge, JudgeReport
from alpha_operator_framework.distill.template_pruner import matches_prune_rule
from alpha_operator_framework.research.field_loader import load_real_market_fields
from alpha_operator_framework.platform.platform_simulator import (
    BrainPlatformSimulator,
    PlatformAlphaResult,
)

logger = logging.getLogger(__name__)


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
        from alpha_operator_framework.carpet.simulation import run_batch_simulation_and_persist

        return run_batch_simulation_and_persist(self, cohort)

    def prune_zero_signal_families(
        self,
        cohort: List[Task],
        results: List[PlatformAlphaResult],
    ) -> List[str]:
        from alpha_operator_framework.carpet.optimization import prune_zero_signal_families

        return prune_zero_signal_families(self, cohort, results)

    def optimize_positive_signals(
        self,
        results: List[PlatformAlphaResult],
    ) -> List[PlatformAlphaResult]:
        from alpha_operator_framework.carpet.optimization import optimize_positive_signals

        return optimize_positive_signals(self, results)

    def distill_and_persist_winning_templates(
        self,
        final_reports: List[JudgeReport],
    ) -> List[str]:
        from alpha_operator_framework.carpet.distillation import distill_and_persist_winning_templates

        return distill_and_persist_winning_templates(self, final_reports)

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


def _run_stratified_carpet_mining_with(
    miner_type,
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

    miner = miner_type(config)
    result = miner.run()

    # 导出研报
    if output_report_path:
        out_p = Path(output_report_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(result.summary_markdown(), encoding="utf-8")
        logger.info(f"已导出研报到: {out_p}")

    return result


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
    return _run_stratified_carpet_mining_with(
        StratifiedCarpetMiner,
        region=region,
        universe=universe,
        datasets=datasets,
        sample_per_family=sample_per_family,
        batch_size=batch_size,
        delay=delay,
        decay=decay,
        neutralization=neutralization,
        truncation=truncation,
        execute=execute,
        seed=seed,
        output_report_path=output_report_path,
    )
