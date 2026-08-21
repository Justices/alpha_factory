"""本地轻量向量化回测沙盒子模块.

提供秒级快速回测能力，在发起云端仿真前提前过滤无预测能力的无效因子。
"""

from .ops import (
    SANDBOX_OPS_MAP,
    cs_rank,
    cs_zscore,
    cs_scale,
    cs_quantile,
    cs_reverse,
    cs_inverse,
    ts_delay,
    ts_delta,
    ts_mean,
    ts_sum,
    ts_std_dev,
    ts_rank,
    ts_decay_linear,
    ts_zscore,
    group_neutralize,
    group_rank,
    group_zscore,
    signed_power,
)
from .market_data import (
    MarketDataCrossSection,
    generate_synthetic_market_data,
)
from .engine import (
    SandboxMetrics,
    SandboxEngine,
    evaluate_expression_local,
)

__all__ = [
    # 算子
    "SANDBOX_OPS_MAP",
    "cs_rank",
    "cs_zscore",
    "cs_scale",
    "cs_quantile",
    "cs_reverse",
    "cs_inverse",
    "ts_delay",
    "ts_delta",
    "ts_mean",
    "ts_sum",
    "ts_std_dev",
    "ts_rank",
    "ts_decay_linear",
    "ts_zscore",
    "group_neutralize",
    "group_rank",
    "group_zscore",
    "signed_power",
    # 数据容器
    "MarketDataCrossSection",
    "generate_synthetic_market_data",
    # 仿真器
    "SandboxMetrics",
    "SandboxEngine",
    "evaluate_expression_local",
]
