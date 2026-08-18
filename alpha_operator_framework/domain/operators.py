"""算子库 — 整合 machine_lib 的算子定义并扩展.

本模块定义四类算子:
  1. basic_ops: 基础变换 (reverse, rank, zscore等)
  2. ts_ops: 时间序列算子 (ts_rank, ts_delta, ts_sum等)
  3. group_ops: 分组算子 (group_neutralize, group_rank等)
  4. extended_ops: 扩展算子 (regression_neut, vector_neut等)

所有算子均为纯函数, 不依赖平台状态。
"""

from typing import Sequence, List, Tuple
import re

# ---------------------------------------------------------------------------
# 算子常量
# ---------------------------------------------------------------------------

# 基础变换算子 (来自 machine_lib)
basic_ops = ["reverse", "inverse", "rank", "zscore", "quantile", "normalize"]

# 时间序列算子 (来自 machine_lib)
ts_ops = [
    "ts_rank", "ts_zscore", "ts_delta", "ts_sum", "ts_delay",
    "ts_std_dev", "ts_mean", "ts_arg_min", "ts_arg_max",
    "ts_scale", "ts_quantile"
]

# 分组算子 (来自 machine_lib group_factory)
group_ops = ["group_neutralize", "group_rank", "group_zscore"]

# 向量归约算子 (将 VECTOR 数据字段转换为标量表达式)quantile
# 顺序与 BRAIN 当前 Vector 分类保持一致，并兼容已有 vec_avg/vec_sum 默认行为。
vec_ops = [
    "vec_avg",
    "vec_sum",
    "vec_min",
    "vec_max",
    "vec_stddev",
    "vec_range",
    "vec_count",
]

# 扩展算子 (来自 cold_templates ACCESS_LIMITED_OPS + machine_lib)
extended_ops = [
    "regression_neut",      # 回归中性化
    "vector_neut",          # 向量正交
    "ts_delta_limit",       # 带约束变化量
    "signed_power",         # 保号幂次
    "ts_decay_linear",      # 线性衰减
    "ts_regression",        # 时间序列回归
]

# 需要更高权限的算子 (普通顾问账户不可用)
ACCESS_LIMITED_OPS = ("regression_neut", "s_log_1p", "vector_neut",
                      "ts_delta_limit", "group_mean")


# ---------------------------------------------------------------------------
# 工厂函数 (来自 machine_lib)
# ---------------------------------------------------------------------------

def ts_factory(op: str, field: str, windows: Sequence[int] = None) -> List[str]:
    """时间序列算子工厂: 对字段应用指定ts算子并展开窗口.

    Args:
        op: ts算子名 (如 ts_rank, ts_delta)
        field: 输入字段表达式
        windows: 窗口列表, 默认 [5, 22, 66, 120, 240]

    Returns:
        表达式列表, 每个窗口一个表达式

    Example:
        >>> ts_factory("ts_rank", "close")
        ['ts_rank(close, 5)', 'ts_rank(close, 22)', ...]
    """
    if windows is None:
        windows = [5, 22, 66, 120, 240]

    return [f"{op}({field}, {w})" for w in windows]


def group_factory(
    op: str,
    field: str,
    region: str,
    field_type: str = "MATRIX",
    category: str = "",
    available_groups: Sequence[str] = ()
) -> List[str]:
    """分组算子工厂: 对字段应用group算子并展开分组.

    Args:
        op: group算子名 (group_neutralize, group_rank, group_zscore)
        field: 输入字段表达式
        region: 地区代码 (USA, EUR, CHN等)
        field_type: 字段类型 (MATRIX, VECTOR)
        category: 字段类别 (可选)
        available_groups: 可用分组字段列表 (优先使用)

    Returns:
        表达式列表, 每个分组一个表达式

    Note:
        本函数仅生成表达式, 不做平台查询.
        实际可用分组需从 alpha_machine.group_candidates 获取.

    Example:
        >>> group_factory("group_rank", "close", "USA")
        ['group_rank(close, densify(sector))', ...]
    """
    # 默认分组 (所有地区通用)
    default_groups = ["market", "sector", "industry", "subindustry"]

    # 如果提供了available_groups, 优先使用
    if available_groups:
        groups = available_groups
    else:
        # 否则使用默认分组 (实际项目应从alpha_machine获取地区特定分组)
        groups = default_groups

    # 生成表达式
    output = []
    for group in groups:
        expr = f"{op}({field}, densify({group}))"
        output.append(expr)

    return output


def first_order_factory(
    fields: Sequence[str],
    ops_set: Sequence[str] = None
) -> List[str]:
    """一阶因子工厂: 对字段集合应用算子集合.

    Args:
        fields: 字段表达式列表
        ops_set: 算子列表, 默认使用 basic_ops + ts_ops

    Returns:
        表达式列表, 每个字段×算子组合一个表达式

    Example:
        >>> first_order_factory(["close", "volume"], ["rank", "ts_rank"])
        ['rank(close)', 'ts_rank(close, 5)', ...]
    """
    if ops_set is None:
        ops_set = basic_ops + ts_ops

    alpha_set = []
    for field in fields:
        # 原始字段也加入 (相当于reverse op)
        alpha_set.append(field)

        for op in ops_set:
            if op.startswith("ts_"):
                # 时间序列算子展开窗口
                alpha_set.extend(ts_factory(op, field))
            elif op == "signed_power":
                alpha_set.append(f"{op}({field}, 2)")
            else:
                alpha_set.append(f"{op}({field})")

    return alpha_set


def second_order_factory(
    first_order_fields: Sequence[str],
    group_ops_set: Sequence[str] = None,
    region: str = "USA",
    available_groups: Sequence[str] = ()
) -> List[str]:
    """二阶因子工厂: 对一阶字段应用group算子.

    整合 machine_lib 的 group_factory 到统一接口.

    Args:
        first_order_fields: 一阶字段表达式列表
        group_ops_set: group算子列表, 默认使用 group_ops
        region: 地区代码
        available_groups: 可用分组字段列表

    Returns:
        表达式列表, 每个一阶字段×group算子×分组一个表达式

    Example:
        >>> second_order_factory(["rank(close)"], region="EUR")
        ['group_neutralize(rank(close), densify(sector))', ...]
    """
    if group_ops_set is None:
        group_ops_set = group_ops

    second_order = []
    for fo_field in first_order_fields:
        for g_op in group_ops_set:
            second_order.extend(
                group_factory(g_op, fo_field, region,
                              field_type="MATRIX", category="",
                              available_groups=available_groups)
            )

    return second_order


def uses_access_limited_op(expression: str) -> List[str]:
    """检测表达式中是否使用了需要更高权限的算子.

    Args:
        expression: 因子表达式

    Returns:
        命中的受限算子列表 (空表示对普通顾问可用)

    Example:
        >>> uses_access_limited_op("vector_neut(a, b)")
        ['vector_neut']
    """
    return [op for op in ACCESS_LIMITED_OPS if op in expression]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_vec_fields(fields: Sequence[str], vec_ops: Sequence[str] = None) -> List[str]:
    """对 VECTOR 字段应用 VEC 算子归约为标量。

    来自 machine_lib.get_vec_fields.

    Args:
        fields: VECTOR字段ID列表
        vec_ops: VEC 算子列表；默认使用全部 ``vec_ops``。

    Returns:
        归约后的标量表达式列表

    Example:
        >>> get_vec_fields(["nws82_sentiment"], ["vec_avg", "vec_count"])
        ['vec_avg(nws82_sentiment)', 'vec_count(nws82_sentiment)']
    """
    if vec_ops is None:
        vec_ops = vec_ops

    vec_fields = []
    for field in fields:
        for vec_op in vec_ops:
            vec_fields.append(f"{vec_op}({field})")

    return vec_fields


def process_datafields(fields_df, vec_ops: Sequence[str] = None) -> List[str]:
    """处理数据字段DataFrame, 生成标量表达式列表.

    来自 machine_lib.process_datafields.

    Args:
        fields_df: 包含 'id' 和 'type' 列的DataFrame
        vec_ops: VECTOR字段的归约操作符

    Returns:
        预处理后的标量表达式列表

    Example:
        输入: DataFrame with columns [id, type]
        输出: ['winsorize(ts_backfill(field1, 120), std=4)', ...]
    """
    datafields = []

    # MATRIX字段直接使用
    matrix_fields = fields_df[fields_df['type'] == "MATRIX"]["id"].tolist()
    datafields.extend(matrix_fields)

    # VECTOR字段归约为标量
    vector_fields = fields_df[fields_df['type'] == "VECTOR"]["id"].tolist()
    datafields.extend(get_vec_fields(vector_fields, vec_ops))

    # 统一预处理: winsorize + ts_backfill
    return [f"winsorize(ts_backfill({f}, 120), std=4)" for f in datafields]


# ---------------------------------------------------------------------------
# 操作符提取
# ---------------------------------------------------------------------------

_FIRST_OP_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def extract_first_operator(expression: str) -> str:
    """返回表达式最左侧函数调用名(第一个操作符).

    用于按操作符分组的分层随机抽样: 同一操作符的表达式归为一组。

    Args:
        expression: alpha表达式, 如 "group_neutralize(ts_rank(close,10),industry)"

    Returns:
        最左侧函数名; 无函数调用时退化为最左侧标识符; 两者皆无返回 "__none__"

    Example:
        >>> extract_first_operator("group_neutralize(ts_rank(close,10),industry)")
        'group_neutralize'
        >>> extract_first_operator("ts_delta(close,252)/ts_delay(close,252)")
        'ts_delta'
        >>> extract_first_operator("")
        '__none__'
    """
    if not expression:
        return "__none__"
    m = _FIRST_OP_RE.search(expression)
    if m:
        return m.group(1)
    m2 = re.search(r"[A-Za-z_][A-Za-z0-9_]*", expression)
    return m2.group(0) if m2 else "__none__"


__all__ = [
    # 算子常量
    "basic_ops",
    "ts_ops",
    "group_ops",
    "vec_ops",
    "extended_ops",
    "ACCESS_LIMITED_OPS",
    # 工厂函数
    "ts_factory",
    "group_factory",
    "first_order_factory",
    "second_order_factory",
    # 辅助函数
    "uses_access_limited_op",
    "get_vec_fields",
    "process_datafields",
    "extract_first_operator",
]
