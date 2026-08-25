"""Workflow configuration and result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

@dataclass
class OptimizeConfig:
    """优化阶段配置."""
    # 筛选方式1: 指定alpha_id列表
    alpha_ids: Optional[List[str]] = None

    # 筛选方式2: 按条件筛选
    min_sharpe: Optional[float] = None
    max_sharpe: Optional[float] = None
    min_fitness: Optional[float] = None
    max_fitness: Optional[float] = None
    min_turnover: Optional[float] = None
    max_turnover: Optional[float] = None

    # 其他筛选条件
    region: Optional[str] = None
    dataset_id: Optional[str] = None
    status: Optional[str] = None

    # 优化参数
    decay_variants: List[float] = field(default_factory=lambda: [3.0, 6.0, 9.0])
    neutralization_variants: List[str] = field(default_factory=lambda: ["MARKET", "SECTOR", "INDUSTRY"])
    max_variants_per_alpha: int = 10

    # 限制
    limit: Optional[int] = None

# 一阶算子冷启动白名单 (顺序即优先级)。
# 证据沉淀 (operator_signal_stats) 之前由这份 curated 顺序兜底;
# 有回测数据后由 select_curated_operators 按 hit_rate 接管挑选。
DEFAULT_FIRST_ORDER_OPS = (
    "rank", "zscore", "ts_rank", "ts_delta", "ts_zscore",
    "quantile", "normalize", "ts_std_dev", "ts_mean", "ts_sum", "ts_delay",
)


@dataclass
class SurveyConfig:
    """Survey阶段配置."""
    region: str = "EUR"
    universe: str = "TOP2500"
    delay: int = 1

    # 数据集选择
    dataset_id: str = ""                    # 空表示全字段
    field_ids: Optional[List[str]] = None   # None表示采样,否则使用指定字段列表

    # 采样参数(仅当field_ids=None时生效)
    sample_n: int = 80                 # 字段池大小
    backtest_sample_n: int = 80        # 一阶表达式抽样回测数量; <=0=全部
    min_coverage: float = 0.5          # 股票截面覆盖闸 (0=不过滤)
    min_date_coverage: float = 0.9       # 平台 dateCoverage 闸 (历史日期覆盖; 0=不过滤)
    prefer_cold: bool = True
    seed: int = 42
    top_n_templates: int = 3  # 用于密度评估的top-N

    # 模板选择
    include_unary: bool = True
    include_raw_first_order: bool = True   # 额外生成裸字段一阶 (rank(close) 等)
    use_template_library: bool = True      # 基于模板类库生成 4 族模板任务
    template_families: Optional[Tuple[str, ...]] = None  # 模板类库启用族 (None=4 族)
    template_categories: Optional[Tuple[str, ...]] = None  # category 过滤 (None=全匹配)
    include_binary: bool = False       # 信号筛选后再走二元分支
    include_ternary: bool = False
    include_quaternary: bool = False
    include_semantic_pairs: bool = True
    include_antonym_pairs: bool = True  # 自动发现相反指标配对 (bullish/bearish 等, difference 语义)
    include_paired_bases: bool = True  # 自动发现复合配对 (net_revision/spread, 带 denominator)
    group_fields: Optional[List[str]] = None

    # 模拟参数
    batch_size: int = 8
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    decay: float = 6.0

    # 第一阶段默认完整计算已选字段的所有组合；sample_n仍用于字段池大小。
    all_combinations: bool = True

    # 算子挑选 (证据驱动, 替代全量展开): None=每轮从 operator_signal_stats
    # 按 hit_rate 挑选 + 冷启动白名单兜底; 显式传Tuple则固定使用
    first_order_ops: Optional[Tuple[str, ...]] = None
    curated_top_n: int = 8                 # 挑选算子上限
    curated_min_trials: int = 3            # 淘汰判定最小样本数
    curated_cold_slots: int = 2            # 冷启动探索名额

    # 模板 operator 槽算子信号回流: 零命中且样本充足(trials>=该值)的算子淘汰, 其余全部展开
    operator_min_trials: int = 3

    # 总量预算: 已回测 alpha (alpha_details) + 本轮回测 <= 该值, 超出则裁剪/跳过
    max_alpha_budget: int = 1000


@dataclass
class DeepenConfig:
    """Deepen阶段配置."""
    # 质量门
    min_sharpe: float = 1.2
    min_fitness: float = 0.7
    min_margin: float = 5.0
    min_turnover: float = 0.01
    max_turnover: float = 0.70

    # 字段扩展
    sample_n: int = 400
    top_n_templates: int = 3


@dataclass
class SignalBranchConfig:
    """一阶信号筛选后的分支配置."""
    min_sharpe: float = 0.7
    min_fitness: float = 0.7
    max_signal_expressions: int = 200
    branch_backtest_sample_n: int = 80  # 每个分支回测数量; <=0=全部
    include_binary: bool = True
    include_second_order: bool = True
    group_ops: Optional[List[str]] = None
    groups: Optional[List[str]] = None


@dataclass
class WorkflowResult:
    """工作流结果."""
    success: bool
    stage: str
    message: str = ""

    # 任务列表
    tasks_generated: int = 0
    tasks_file: Optional[Path] = None

    # 模拟结果
    simulations_run: int = 0
    results_file: Optional[Path] = None

    # 密度评估
    density_report: Optional[Dict] = None
    top_templates: List[Dict] = field(default_factory=list)

    # 候选alpha
    candidates: List[Dict] = field(default_factory=list)
    kept_file: Optional[Path] = None

    # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    config: Dict = field(default_factory=dict)


__all__ = [
    "DEFAULT_FIRST_ORDER_OPS",
    "OptimizeConfig",
    "SurveyConfig",
    "DeepenConfig",
    "SignalBranchConfig",
    "WorkflowResult",
]
