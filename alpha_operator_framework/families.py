"""模板族工厂 — 整合 cold_templates 的结构正交模板并扩展多阶支持.

本模块定义:
  1. 一元模板 (UNARY_TEMPLATES): 10个单字段操作模板
  2. 二元模板 (BINARY_TEMPLATES): 8个两字段回归/正交模板
  3. 三元模板 (TERNARY_TEMPLATES): 7个三字段联合/条件切换模板
  4. 四元模板 (QUATERNARY_TEMPLATES): 扩展支持多阶group操作

模板设计原则 (来自cold_templates):
  * 结构正交: 每个index在结构上与其他index不重复
  * 降低self-corr: 从模板底层避免堆叠相同操作符
  * 因子密度: 通过密度评估筛选最适合当前数据集的模板
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Sequence, List, Tuple


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Task:
    """一个待回测的模板实例.

    与 alpha_machine.simulate 的 {expression, decay} shape 兼容。
    扩展字段:
      - template_index: 模板在族内的序号
      - family: 族名 (unary/binary/ternary/quaternary)
      - fields_per_alpha: 字段数 (用于三元预警)
      - base_fields: 基础字段元组
      - meta: 元数据字典
    """

    expression: str
    template_index: int
    family: str  # "unary" | "binary" | "ternary" | "quaternary"
    fields_per_alpha: int
    decay: float = 6.0
    base_fields: Tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)

    def to_sim_dict(self) -> dict:
        """转成 alpha_machine.simulate 期望的 {expression, decay} 字典."""
        return {"expression": self.expression, "decay": float(self.decay)}


# ---------------------------------------------------------------------------
# 模板常量 — cold_templates 原貌 (便于对照/引用)
# ---------------------------------------------------------------------------

UNARY_TEMPLATES: Tuple[Tuple[int, str, str, int], ...] = (
    (0,  "ts_regression(ts_zscore({a}, 500), ts_step(1), 500, rettype=2)", "斜率: zscore序列对时间步长的回归斜率", 1),
    (1,  "ts_delta(ts_delta({a}, 252)/ts_delay({a}, 252), 252)",            "增长率二阶: 增长率的再变化", 1),
    (2,  "ts_delta({a}, 252)/ts_delay({a}, 252)",                           "增长率: 当期变化相对滞后值", 1),
    (3,  "ts_regression(ts_delta({a}, 252), ts_delta({a}, 500), 500, rettype=2)", "自回归斜率: 短窗口delta对长窗口delta回归", 1),
    (4,  "ts_mean(signed_power(ts_delta({a}, 252), 2), 500)",               "平方动量: 保号放大的动量长期均值", 1),
    (5,  "ts_decay_linear(ts_delta({a}, 252), 500)",                        "衰减动量: 线性衰减加权的动量", 1),
    (6,  "reverse(ts_rank(ts_zscore({a}, 500), 500))",                      "排名反转: 高位反转做空", 1),
    (7,  "log(abs(ts_delta({a}, 500)) + 0.000001)",                         "对数平滑: 对数压缩长窗口变化幅度", 1),
    (8,  "signed_power(ts_delta({a}, 500), 2)",                             "符号幂: 保号放大的长窗口动量", 1),
    (9,  "ts_delta(ts_delta({a}, 252), 500)",                               "差分层叠: 变化的再变化(加速度)", 1),
)

BINARY_TEMPLATES: Tuple[Tuple[int, str, str, int], ...] = (
    (0, "ts_regression(ts_zscore({a}, 500), ts_zscore({b}, 500), 500)",         "联合zscore回归斜率", 2),
    (1, "ts_regression(ts_zscore({a}, 500), ts_zscore({b}, 500), 500, rettype=2)", "联合zscore回归残差", 2),
    (2, "ts_regression(ts_zscore({a}, 500), ts_zscore({b}, 500), 500, rettype=6)", "联合zscore回归t值", 2),
    (3, "ts_regression({a}, {b}, 252, rettype=2)",                              "短窗口回归残差", 2),
    (4, "ts_regression({a}, {b}, 500, rettype=2)",                             "长窗口回归残差", 2),
    (5, "regression_neut(s_log_1p({a}), s_log_1p({b}))",                       "对数回归中性化残差", 2),
    (6, "vector_neut({a}, {b})",                                                "向量正交: a去除b的成分", 2),
    (7, "ts_delta_limit({a}, {b}, limit_volume=0.1)",                          "带约束变化量: 以b为基准的限制变化", 2),
)

TERNARY_TEMPLATES: Tuple[Tuple[int, str, str, int], ...] = (
    (0, "vector_neut(vector_neut({a}, {b}), {c})",                                     "联合中性化: a对b与c依次正交", 3),
    (1, "regression_neut(regression_neut({a}, {b}), {c})",                             "分层回归残差: 先对b再对c", 3),
    (2, "ts_delta_limit({a}, ({b} + {c}) / 2, limit_volume=0.1)",                       "带约束变化: 以b,c均值为基准的delta limit", 3),
    (3, "ts_corr(ts_zscore({a}, 252), ts_zscore({b}, 252), 252) * {c}",                 "三变量时序相关: a-b相关性以c加权", 3),
    (4, "ts_rank(group_mean({a}, weight, {b}), 500) * {c}",                            "动态排序择时: a在b分组内ts_rank再以c加权", 3),
    (5, "ts_zscore({a}, 500) * ts_zscore({b}, 500) * ts_zscore({c}, 500)",             "三重交互: 三个标准化信号相乘(非线性放大)", 3),
    (6, "if_else({c} > ts_mean({c}, 500), {a}, {b})",                                  "条件切换: c高位选a否则b", 3),
)

# 新增: 四元模板 (扩展多阶group操作)
# 使用 machine_lib 的 group_ops 作为第四元素
QUATERNARY_TEMPLATES: Tuple[Tuple[int, str, str, int], ...] = (
    (0, "group_neutralize(vector_neut({a}, {b}), {c})",                         "group正交: 先向量正交再分组中性化", 4),
    (1, "group_rank(vector_neut({a}, {b}), {c})",                                "group排名: 向量正交后再分组排名", 4),
    (2, "group_zscore(ts_regression({a}, {b}, 252, rettype=2), {c})",           "group标准化: 回归残差的分组标准化", 4),
    (3, "ts_delta_limit(group_neutralize({a}, {c}), {b}, limit_volume=0.1)",    "group约束: 分组中性化后带约束变化", 4),
    (4, "if_else({d} > ts_mean({d}, 500), group_neutralize({a}, {c}), {b})",    "条件group: 高位分组中性化否则选b", 4),
)


# ---------------------------------------------------------------------------
# 窗口路由 — cold_templates 评论区 36380851
# ---------------------------------------------------------------------------

# 经济学标准窗口 (匹配 CLAUDE.md Economic Window Constraint)
STANDARD_WINDOWS = (5, 22, 66, 120, 252, 504)

# 按数据更新频率的推荐窗口
FREQUENCY_WINDOWS = {
    "daily":     (22, 63, 126),
    "monthly":   (252, 500, 750),
    "quarterly": (252, 500, 750),
    "unknown":   (252, 500),  # fallback
}


def windows_for_frequency(frequency: str) -> Tuple[int, ...]:
    """按数据更新频率返回推荐窗口.

    Args:
        frequency: 数据更新频率 (daily/monthly/quarterly)

    Returns:
        推荐窗口元组

    Example:
        >>> windows_for_frequency("daily")
        (22, 63, 126)
    """
    return FREQUENCY_WINDOWS.get((frequency or "unknown").lower(), FREQUENCY_WINDOWS["unknown"])


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def _render(template: str, mapper: dict) -> str:
    """安全渲染 — 仅替换 {a}/{b}/{c}/{d}/{window}, 不动表达式里其它花括号."""
    class _SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    return template.format_map(_SafeDict(mapper))


def unary_factory(
    scalar_fields: Iterable[str],
    *,
    windows: Sequence[int] | None = None,
    include_raw_idx: bool = True,
) -> List[Task]:
    """一元模板工厂: 对每个标量字段展开10个模板.

    Args:
        scalar_fields: 已预处理的标量表达式列表
        windows: 额外按窗口展开的变体窗口集
        include_raw_idx: 是否包含帖子主楼原貌(默认True)

    Returns:
        Task列表, 每个字段×模板一个任务

    Example:
        >>> tasks = unary_factory(["close", "volume"])
        >>> len(tasks)
        20  # 2 fields × 10 templates
    """
    tasks: List[Task] = []
    fields = list(scalar_fields)

    for a in fields:
        for idx, template, rationale, fpa in UNARY_TEMPLATES:
            if include_raw_idx:
                expr = _render(template, {"a": a})
                tasks.append(Task(
                    expression=expr,
                    template_index=idx,
                    family="unary",
                    fields_per_alpha=fpa,
                    base_fields=(a,),
                    meta={"label": rationale, "window": 500, "source_freq": "unknown"},
                ))

    return tasks


def binary_factory(
    scalar_fields: Iterable[str],
    *,
    max_pairs: int | None = None,
) -> List[Task]:
    """二元模板工厂: 字段两两组合×8个模板.

    Args:
        scalar_fields: 标量表达式列表
        max_pairs: 限制配对总数(防止爆额度)

    Returns:
        Task列表, 每对字段×模板一个任务

    Example:
        >>> tasks = binary_factory(["close", "volume", "returns"])
        >>> len(tasks)
        24  # C(3,2)=3 pairs × 8 templates
    """
    fields = list(scalar_fields)
    pairs = list(combinations(fields, 2))

    if max_pairs is not None and len(pairs) > max_pairs:
        pairs = pairs[:max_pairs]

    tasks: List[Task] = []
    for a, b in pairs:
        for idx, template, rationale, fpa in BINARY_TEMPLATES:
            tasks.append(Task(
                expression=_render(template, {"a": a, "b": b}),
                template_index=idx,
                family="binary",
                fields_per_alpha=fpa,
                base_fields=(a, b),
                meta={"label": rationale, "window": 500, "source_freq": "unknown"},
            ))

    return tasks


def ternary_factory(
    scalar_fields: Iterable[str],
    *,
    max_triples: int | None = None,
) -> List[Task]:
    """三元模板工厂: 字段三三组合×7个模板.

    Args:
        scalar_fields: 标量表达式列表
        max_triples: 限制三元组总数

    Returns:
        Task列表, 每个三元组×模板一个任务

    Example:
        >>> tasks = ternary_factory(["close", "volume", "returns", "cap"])
        >>> len(tasks)
        28  # C(4,3)=4 triples × 7 templates
    """
    fields = list(scalar_fields)
    triples = list(combinations(fields, 3))

    if max_triples is not None and len(triples) > max_triples:
        triples = triples[:max_triples]

    tasks: List[Task] = []
    for a, b, c in triples:
        for idx, template, rationale, fpa in TERNARY_TEMPLATES:
            tasks.append(Task(
                expression=_render(template, {"a": a, "b": b, "c": c}),
                template_index=idx,
                family="ternary",
                fields_per_alpha=fpa,
                base_fields=(a, b, c),
                meta={"label": rationale, "window": 500, "source_freq": "unknown"},
            ))

    return tasks


def quaternary_factory(
    scalar_fields: Iterable[str],
    group_fields: Sequence[str],
    *,
    max_quadruples: int | None = None,
) -> List[Task]:
    """四元模板工厂: 字段三三组合×group字段×5个模板.

    扩展模板, 整合 machine_lib 的 group_ops 到 cold_templates 框架。

    Args:
        scalar_fields: 标量表达式列表
        group_fields: GROUP字段列表 (如 ["sector", "industry"])
        max_quadruples: 限制四元组总数

    Returns:
        Task列表, 每个组合×模板一个任务

    Example:
        >>> tasks = quaternary_factory(
        ...     ["close", "volume", "returns"],
        ...     ["sector", "industry"]
        ... )
        >>> len(tasks)  # C(3,2)=3 pairs × 2 groups × 5 templates
        30
    """
    fields = list(scalar_fields)
    pairs = list(combinations(fields, 2))

    if max_quadruples is not None and len(pairs) > max_quadruples:
        pairs = pairs[:max_quadruples]

    tasks: List[Task] = []
    for a, b in pairs:
        for g in group_fields:
            for idx, template, rationale, fpa in QUATERNARY_TEMPLATES:
                # {c} 代表group字段, {d} 可选的条件字段
                tasks.append(Task(
                    expression=_render(template, {"a": a, "b": b, "c": g, "d": "cap"}),
                    template_index=idx,
                    family="quaternary",
                    fields_per_alpha=fpa,
                    base_fields=(a, b, g),
                    meta={"label": rationale, "window": 500, "source_freq": "unknown", "group": g},
                ))

    return tasks


__all__ = [
    # 模板常量
    "UNARY_TEMPLATES",
    "BINARY_TEMPLATES",
    "TERNARY_TEMPLATES",
    "QUATERNARY_TEMPLATES",
    "STANDARD_WINDOWS",
    "FREQUENCY_WINDOWS",
    # 数据结构
    "Task",
    # 工厂函数
    "unary_factory",
    "binary_factory",
    "ternary_factory",
    "quaternary_factory",
    "windows_for_frequency",
]