"""字段预处理 — 整合 machine_lib 的字段处理与 cold_templates 的采样逻辑.

本模块提供:
  1. FieldSpec: 字段规格数据结构 (来自 alpha_machine)
  2. preprocess_field: 字段预处理 (winsorize + ts_backfill)
  3. candidate_scalars: 候选字段筛选 (过BARRIER并排序)
  4. sample_scalar_expressions: 字段池采样 (随机80组合)

设计红线:
  * 本模块不碰网络, FieldSpec 由 alpha_machine.fetch_datafields 提供
  * 预处理后的标量表达式直接喂 families 工厂
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence, List, Tuple

from alpha_operator_framework.domain.operators import vec_ops


DEFAULT_VEC_OPS = tuple(vec_ops)


# ---------------------------------------------------------------------------
# 字段规格 — alpha_machine.FieldSpec 的简化版
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    """字段规格 (从平台数据字段行构造)."""

    id: str                          # 字段ID
    dataset_id: str                  # 数据集ID
    type: str                        # MATRIX / VECTOR / GROUP
    coverage: float = 0.0            # 覆盖率 (股票截面覆盖)
    date_coverage: float = 0.0       # 日期覆盖率 (历史天数覆盖; 平台 dateCoverage)
    user_count: int = 0              # 使用人数
    alpha_count: int = 0             # alpha计数
    name: str = ""                   # 字段名(可选)
    description: str = ""            # 描述(可选)
    economic_type: str = ""          # price / return / volume / fundamental_flow ...
    frequency: str = ""              # daily / monthly / quarterly
    signedness: str = ""             # signed / nonnegative / positive
    scale: str = ""                  # level / ratio / bounded / categorical
    category: str = ""               # 平台字段分类 (analyst/pv/model/fundamental...)
    coverage_stability: float = 1.0  # 覆盖率历史稳定性 (0~1.0)
    crowding_score: float = 0.0      # 拥挤度得分 (越高越拥挤)
    novelty_priority: float = 1.0    # 新颖度加权 (另类数据新颖度更高)

    @property
    def quality_priority_score(self) -> float:
        """计算字段准入画像优先级得分 (高覆盖、低拥挤、高新颖度优先)."""
        cov_part = self.coverage * 40.0
        crowd_penalty = min(30.0, (self.user_count / 100.0) * 15.0 + (self.alpha_count / 500.0) * 15.0)
        novelty_part = self.novelty_priority * 30.0
        return max(0.0, round(cov_part - crowd_penalty + novelty_part, 2))



@dataclass(frozen=True)
class ScalarField:
    """预处理后的标量表达式 + 来源字段元数据 (供模板创建策略按 category 匹配)."""

    expr: str          # 预处理后的标量表达式 (如 winsorize(ts_backfill(close,120),std=4))
    category: str      # 来源 FieldSpec.category (可能 "")
    field_id: str      # 来源 FieldSpec.id


# ---------------------------------------------------------------------------
# 字段预处理 — machine_lib.process_datafields 的单字段版本
# ---------------------------------------------------------------------------

def preprocess_field(
    field: FieldSpec,
    *,
    backfill: int = 120,
    winsorize_std: float = 4.0,
    vector_ops: Tuple[str, ...] = DEFAULT_VEC_OPS
) -> List[str]:
    """单个字段预处理 → 标量表达式列表.

    MATRIX字段: 直接winsorize + ts_backfill
    VECTOR 字段: 对每个配置的 VEC 算子归约后，再预处理
    EVENT 字段: 固定以 vec_avg 归约后，再预处理
    GROUP字段: 不做预处理(不作为原子信号)

    Args:
        field: 字段规格
        backfill: 回填窗口
        winsorize_std: 缩尾标准差
        vector_ops: VECTOR字段的归约操作符

    Returns:
        预处理后的标量表达式列表

    Example:
        >>> spec = FieldSpec(id="close", dataset_id="pv1", type="MATRIX")
        >>> preprocess_field(spec)
        ['winsorize(ts_backfill(close, 120), std=4)']
    """
    if field.type == "GROUP":
        return []  # GROUP字段不作为原子信号

    expressions = []

    if field.type == "MATRIX":
        # MATRIX字段直接预处理
        expr = f"winsorize(ts_backfill({field.id}, {backfill}), std={winsorize_std})"
        expressions.append(expr)

    elif field.type == "VECTOR":
        # VECTOR字段先归约再预处理
        for vec_op in vector_ops:
            vec_expr = f"{vec_op}({field.id})"
            expr = f"winsorize(ts_backfill({vec_expr}, {backfill}), std={winsorize_std})"
            expressions.append(expr)

    elif field.type == "EVENT":
        vec_expr = f"vec_avg({field.id})"
        expressions.append(f"winsorize(ts_backfill({vec_expr}, {backfill}), std={winsorize_std})")

    return expressions


def preprocess_fields_rotated(
    fields: Sequence[FieldSpec],
    *,
    backfill: int = 120,
    winsorize_std: float = 4.0,
    vector_ops: Tuple[str, ...] = DEFAULT_VEC_OPS,
    seed: Optional[int] = None,
) -> List[Tuple[FieldSpec, str]]:
    """多字段预处理, VECTOR 字段按轮转分配聚合算子 —— 生成层消除近亲冗余.

    背景: ``preprocess_field`` 对每个 VECTOR 字段展开全部 vector_ops 变体
    (vec_avg/vec_sum/vec_min/... × 字段), 后续工厂再乘上一阶算子/模板,
    产生大量"结构相同仅聚合算子不同"的近亲表达式 (实测候选池 80% 冗余)。

    本函数按字段轮转分配聚合算子: 每个 VECTOR 字段只归约 1 次,
    全局算子多样性保留 (第 i 个 VECTOR 字段用 vector_ops[i % len], 种子打乱顺序),
    生成量降为 1/len(vector_ops)。

    Returns:
        每个非 GROUP 字段 → (FieldSpec, 标量表达式) 对; GROUP 字段不产出。
    """
    ops = list(vector_ops)
    if seed is not None:
        random.Random(seed).shuffle(ops)  # 打乱轮转顺序, 避免字段排列偏差
    out: List[Tuple[FieldSpec, str]] = []
    vi = 0
    for f in fields:
        if f.type == "GROUP":
            continue
        if f.type == "VECTOR":
            op = ops[vi % len(ops)]
            vi += 1
            exprs = preprocess_field(f, backfill=backfill, winsorize_std=winsorize_std, vector_ops=(op,))
        else:
            exprs = preprocess_field(f, backfill=backfill, winsorize_std=winsorize_std)
        out.extend((f, e) for e in exprs)
    return out


# ---------------------------------------------------------------------------
# 字段池采样 — cold_templates.fields_pool
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SampleSpec:
    """采样规格."""

    sample_n: int = 80            # 帖子的80组合
    min_coverage: float = 0.0     # 可选coverage闸 (股票截面覆盖)
    min_date_coverage: float = 0.0  # 可选dateCoverage闸 (历史日期覆盖; 0=不过滤)
    backfill: int = 120
    winsorize_std: float = 4.0
    vector_ops: Tuple[str, ...] = DEFAULT_VEC_OPS
    prefer_cold: bool = True      # True: 低userCount优先 (蓝海降PC)
    seed: int | None = 42
    all_combinations: bool = False  # 组合阶段是否保留全部组合


def candidate_scalars(
    fields: Sequence[FieldSpec],
    spec: SampleSpec = SampleSpec()
) -> List[FieldSpec]:
    """过BARRIER并按冷门偏好排序的字段序列(尚未预处理).

    BARRIER:
      - type ∈ MATRIX/VECTOR (GROUP不当原子信号)
      - coverage ≥ min_coverage
      - date_coverage ≥ min_date_coverage (缺失按0, 会被非零闸挡掉; 0=不过滤)

    排序:
      - prefer_cold=True: 冷门优先(低userCount, 高coverage保留信息量)
      - prefer_cold=False: coverage高优先

    Args:
        fields: 字段规格列表
        spec: 采样规格

    Returns:
        排序后的候选字段列表

    Example:
        >>> fields = [FieldSpec(id="f1", dataset_id="d1", type="MATRIX", coverage=0.9, user_count=5)]
        >>> candidates = candidate_scalars(fields, SampleSpec(min_coverage=0.5))
        >>> len(candidates)
        1
    """
    eligible = [
        f for f in fields
        if f.type in ("MATRIX", "VECTOR")
        and (f.coverage or 0) >= spec.min_coverage
        and (getattr(f, "date_coverage", 0) or 0) >= spec.min_date_coverage
    ]

    if spec.prefer_cold:
        # 冷门优先: userCount升序; 同userCount按coverage降序保留信息量
        eligible.sort(key=lambda f: (f.user_count, -f.coverage, f.id))
    else:
        # coverage高优先
        eligible.sort(key=lambda f: (-f.coverage, f.user_count, f.id))

    return eligible


def sample_scalar_expressions(
    fields: Sequence[FieldSpec],
    spec: SampleSpec = SampleSpec()
) -> List[str]:
    """字段池采样 → 预处理后的标量表达式列表.

    步骤:
      1. 过BARRIER并排序
      2. 确定性shuffle (带seed可复现)
      3. 截断到sample_n
      4. 预处理成标量表达式

    Args:
        fields: 字段规格列表
        spec: 采样规格

    Returns:
        预处理后的标量表达式列表

    Example:
        >>> fields = [FieldSpec(id="f1", dataset_id="d1", type="MATRIX", coverage=0.9)]
        >>> exprs = sample_scalar_expressions(fields, SampleSpec(sample_n=10))
        >>> len(exprs)
        1
    """
    selected_fields = sample_field_specs(fields, spec)

    # 预处理: 每个FieldSpec → 标量表达式列表
    out: List[str] = []
    for spec_field in selected_fields:
        out.extend(preprocess_field(
            spec_field,
            backfill=spec.backfill,
            winsorize_std=spec.winsorize_std,
            vector_ops=spec.vector_ops,
        ))

    return out


def sample_scalar_field_pairs(
    fields: Sequence[FieldSpec],
    spec: SampleSpec = SampleSpec(),
) -> List[ScalarField]:
    """字段池采样 → 预处理标量表达式 + 来源字段元数据.

    与 ``sample_scalar_expressions`` 完全同 seed 同输出(expr 序列一致), 但额外保留
    来源 FieldSpec 的 category/id, 供模板创建策略按模板 category 匹配字段。

    Args:
        fields: 字段规格列表
        spec: 采样规格

    Returns:
        ScalarField 列表 (expr/category/field_id)
    """
    selected_fields = sample_field_specs(fields, spec)
    out: List[ScalarField] = []
    for spec_field in selected_fields:
        for expr in preprocess_field(
            spec_field,
            backfill=spec.backfill,
            winsorize_std=spec.winsorize_std,
            vector_ops=spec.vector_ops,
        ):
            out.append(ScalarField(expr=expr, category=spec_field.category, field_id=spec_field.id))
    return out


def sample_field_specs(
    fields: Sequence[FieldSpec],
    spec: SampleSpec = SampleSpec(),
) -> List[FieldSpec]:
    """按采样规格返回实际进入表达式生成的字段。"""
    eligible = candidate_scalars(fields, spec)
    rng = random.Random(spec.seed)

    # 采样: 先shuffle打破"冷门全在前"的截断偏差, 再截断到sample_n
    shuffled = list(eligible)
    rng.shuffle(shuffled)

    if spec.sample_n > 0:
        shuffled = shuffled[:spec.sample_n]

    return shuffled


def sample_pair_combinations(
    fields: Sequence[FieldSpec],
    spec: SampleSpec = SampleSpec()
) -> List[Tuple[str, str]]:
    """二元字段池采样 → 预处理后字段两两组合.

    Args:
        fields: 字段规格列表
        spec: 采样规格

    Returns:
        字段对列表

    Example:
        >>> fields = [
        ...     FieldSpec(id="f1", dataset_id="d1", type="MATRIX", coverage=0.9),
        ...     FieldSpec(id="f2", dataset_id="d1", type="MATRIX", coverage=0.9)
        ... ]
        >>> pairs = sample_pair_combinations(fields, SampleSpec(sample_n=5))
        >>> pairs[0]
        ('winsorize(ts_backfill(f1, 120), std=4)', 'winsorize(ts_backfill(f2, 120), std=4)')
    """
    scalars = sample_scalar_expressions(fields, spec)
    pairs = list(combinations(scalars, 2))
    rng = random.Random(spec.seed)
    rng.shuffle(pairs)

    if spec.sample_n > 0 and not spec.all_combinations:
        pairs = pairs[:spec.sample_n]

    return pairs


def sample_triple_combinations(
    fields: Sequence[FieldSpec],
    spec: SampleSpec = SampleSpec()
) -> List[Tuple[str, str, str]]:
    """三元字段池采样 → 预处理后字段三三组合.

    Args:
        fields: 字段规格列表
        spec: 采样规格

    Returns:
        字段三元组列表

    Example:
        >>> fields = [
        ...     FieldSpec(id="f1", dataset_id="d1", type="MATRIX", coverage=0.9),
        ...     FieldSpec(id="f2", dataset_id="d1", type="MATRIX", coverage=0.9),
        ...     FieldSpec(id="f3", dataset_id="d1", type="MATRIX", coverage=0.9)
        ... ]
        >>> triples = sample_triple_combinations(fields, SampleSpec(sample_n=5))
        >>> len(triples[0])
        3
    """
    scalars = sample_scalar_expressions(fields, spec)
    triples = list(combinations(scalars, 3))
    rng = random.Random(spec.seed)
    rng.shuffle(triples)

    if spec.sample_n > 0 and not spec.all_combinations:
        triples = triples[:spec.sample_n]

    return triples


__all__ = [
    "FieldSpec",
    "ScalarField",
    "SampleSpec",
    "preprocess_field",
    "candidate_scalars",
    "sample_field_specs",
    "sample_scalar_expressions",
    "sample_scalar_field_pairs",
    "sample_pair_combinations",
    "sample_triple_combinations",
]
