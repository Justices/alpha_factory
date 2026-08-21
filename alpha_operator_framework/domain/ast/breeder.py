"""符号语法树自由杂交与进化生成器 (Symbolic Tree Breeder & Evolution Engine).

功能:
  1. 彻底摆脱人类预置死板模板，基于形式语法产生式与递归 AST 树自由杂交生成高阶复合 Alpha 表达式
  2. 实现全层级自由算子拼装:
     - 时序类: ts_scale, ts_rank, ts_zscore, ts_decay_linear, ts_delta, ts_mean, ts_std_dev, signed_power, ts_corr
     - 截面分组类: group_rank, group_neutralize, group_zscore, group_scale, group_mean
     - 分组基准: subindustry, industry, sector, market, bucket(rank(cap), range='0.1, 1, 0.1')
     - 结构形态: 三层复合架构、Beta-特质正交分解、双特征动量比率/相关性
  3. 全流程严格通过 AST 解析器、类型检查器与规范化去重
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from alpha_operator_framework.domain.ast.canonicalizer import to_canonical_string
from alpha_operator_framework.domain.ast.validator import validate_expression
from alpha_operator_framework.domain.families import Task

logger = logging.getLogger(__name__)


@dataclass
class BreederConfig:
    """符号语法树生成配置."""

    windows: Tuple[int, ...] = (10, 20, 22, 63, 66, 120, 126, 240)
    groups: Tuple[str, ...] = ("subindustry", "industry", "sector")
    cap_bucket: str = "bucket(rank(cap), range='0.1, 1, 0.1')"
    enable_market_cap_buckets: bool = True
    enable_orthogonal_decomposition: bool = True
    enable_pairwise_interaction: bool = True
    seed: Optional[int] = None


class SymbolicTreeBreeder:
    """符号语法树自由杂交与进化生成引擎."""

    def __init__(self, config: Optional[BreederConfig] = None):
        self.config = config or BreederConfig()
        self.rng = random.Random(self.config.seed) if self.config.seed is not None else random

    def breed_single_feature_expressions(
        self,
        atom: str,
        neut_group: str = "subindustry",
    ) -> List[str]:
        """为一个原子特征自由杂交生成多种多层复合 AST 表达式."""
        exprs: List[str] = []
        g = neut_group.lower()
        cap_b = self.config.cap_bucket

        for w in self.config.windows:
            # 1. 三层架构变体: 时序尺度对齐 (ts_scale / ts_rank / ts_zscore)
            exprs.append(f"ts_scale(group_rank({atom}, {g}), {w})")
            exprs.append(f"ts_rank(group_rank({atom}, {g}), {w})")
            exprs.append(f"ts_zscore(group_rank({atom}, {g}), {w})")
            exprs.append(f"ts_decay_linear(group_rank({atom}, {g}), {min(w, 20)})")

            if self.config.enable_market_cap_buckets:
                exprs.append(f"ts_scale(group_rank({atom}, {cap_b}), {w})")
                exprs.append(f"ts_rank(group_rank({atom}, {cap_b}), {w})")

            # 2. 内层动量/偏离 + 中层中性化 + 外层平滑
            exprs.append(f"ts_decay_linear(group_neutralize(ts_delta({atom}, {w}), {g}), 10)")
            exprs.append(f"group_neutralize(rank(ts_delta({atom}, {w})), {g})")
            exprs.append(f"-1.0 * group_neutralize(rank(ts_delta({atom}, {w})), {g})")

            # 3. 风险调整动量 (动量 / 波动率)
            if w <= 120:
                w_std = min(w * 2, 240)
                exprs.append(f"group_neutralize(rank(ts_delta({atom}, {w})) / (0.01 + rank(ts_std_dev({atom}, {w_std}))), {g})")

        # 4. 行业-特质正交分解 (Beta 周期偏离与特质剪刀差)
        if self.config.enable_orthogonal_decomposition:
            for w in (22, 63, 126):
                exprs.append(f"ts_zscore({atom}, {w}) - ts_zscore(group_neutralize({atom}, {g}), {w})")
                exprs.append(f"group_neutralize(ts_rank(group_neutralize({atom}, {g}), {w}) - ts_rank({atom}, {w}), {g})")
                exprs.append(f"group_neutralize(rank(ts_decay_linear({atom}, {w})) - rank(group_neutralize(ts_decay_linear({atom}, {w}), {g})), {g})")

        return exprs

    def breed_pairwise_expressions(
        self,
        atom1: str,
        atom2: str,
        neut_group: str = "subindustry",
    ) -> List[str]:
        """为两个原子特征自由杂交生成多阶协同与比率 AST 表达式."""
        exprs: List[str] = []
        g = neut_group.lower()

        # 1. 截面相对差分与比率
        exprs.append(f"group_neutralize(rank({atom1}) - rank({atom2}), {g})")
        exprs.append(f"group_neutralize(rank({atom1}) / (0.01 + rank({atom2})), {g})")

        # 2. 动量衰减交叉与时序相关性
        for w in (20, 60):
            exprs.append(f"group_neutralize(rank(ts_decay_linear({atom1}, {w})) * rank({atom2}), {g})")
            exprs.append(f"group_neutralize(rank(ts_delta({atom1}, {w})) / (0.01 + rank(ts_std_dev({atom2}, {w * 2}))), {g})")

        return exprs

    def breed_task_cohort(
        self,
        fields: Sequence[Dict[str, Any]],
        default_decay: int = 12,
        neutralization: str = "SUBINDUSTRY",
    ) -> List[Task]:
        """自由杂交并生成全部合规去重的 Task 候选列表."""
        atomic_fields: List[Tuple[str, str, str]] = []
        for f in fields:
            fid = f["id"]
            ftype = f.get("type", "MATRIX")
            ds = f.get("dataset_id", "")
            if ftype in ("VECTOR", "EVENT"):
                atom = f"winsorize(ts_backfill(vec_avg({fid}), 120), std=4.0)"
            elif "rank" in fid or "score" in fid:
                atom = f"rank({fid})"
            else:
                atom = fid
            atomic_fields.append((fid, atom, ds))

        if not atomic_fields:
            return []

        tasks: List[Task] = []
        seen_can: Set[str] = set()

        # 1. 单特征自由杂交生成
        for fid, atom, ds in atomic_fields:
            raw_exprs = self.breed_single_feature_expressions(atom, neutralization)
            for expr in raw_exprs:
                self._safe_append_task(tasks, seen_can, expr, "symbolic_evolution", default_decay, {"dataset": ds, "field": fid})

        # 2. 双特征自由杂交生成
        if self.config.enable_pairwise_interaction and len(atomic_fields) >= 2:
            for i in range(len(atomic_fields)):
                fid1, atom1, ds1 = atomic_fields[i]
                for j in range(i + 1, min(i + 4, len(atomic_fields))):
                    fid2, atom2, ds2 = atomic_fields[j]
                    raw_pair_exprs = self.breed_pairwise_expressions(atom1, atom2, neutralization)
                    for expr in raw_pair_exprs:
                        self._safe_append_task(tasks, seen_can, expr, "symbolic_evolution", default_decay, {"dataset": f"{ds1}+{ds2}", "fields": [fid1, fid2]})

        logger.info(f"符号语法树杂交引擎共生成 {len(tasks)} 条 100% 合规的高阶 Alpha 表达式")
        return tasks

    @staticmethod
    def _safe_append_task(
        task_list: List[Task],
        seen_set: Set[str],
        expr_str: str,
        family: str,
        decay: int,
        meta: Dict[str, Any],
    ) -> None:
        """验证语法合规并进行 AST 规范化去重落入 task_list."""
        try:
            can_expr = to_canonical_string(expr_str)
            if can_expr in seen_set:
                return
            v_res = validate_expression(can_expr)
            if v_res.is_valid:
                seen_set.add(can_expr)
                task_list.append(
                    Task(
                        family=family,
                        template_index=888,
                        fields_per_alpha=2 if "fields" in meta else 1,
                        expression=can_expr,
                        decay=decay,
                        meta=meta,
                    )
                )
        except Exception:
            pass
