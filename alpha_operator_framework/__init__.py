"""Alpha Operator Framework — 整合 machine_lib 多阶因子与 cold_templates 模板方法论.

本包提供:
  1. families: 一元/二元/三元结构正交模板族 + 多阶group扩展
  2. operators: 算子库 (basic_ops, ts_ops, group_ops, extended_ops)
  3. fields: 字段预处理 (MATRIX/VECTOR/GROUP, 多阶组合)
  4. density: 因子密度评估 (信号门, 模板聚合, top-N筛选)
  5. pruning: 三阶段剪枝 (语义剪枝/同字段top-k/相关性剪枝)
  6. evaluation: Alpha评价 (FailedGate计数/数据集质量预筛/综合评级)
  7. orchestrator: survey→deepen→submit 三段工作流

设计红线:
  * families/operators/density/pruning 纯函数 (pruning.correlation_prune 例外, 平台只读)
  * 模拟统一经 alpha_machine.simulate (brain_client单例)
  * submit默认dry-run, 需显式 --execute 才触发check
"""

__version__ = "0.1.0"

from .families import (
    UNARY_TEMPLATES,
    BINARY_TEMPLATES,
    TERNARY_TEMPLATES,
    QUATERNARY_TEMPLATES,  # 新增: 多阶group模板
    Task,
    unary_factory,
    first_order_task_factory,
    economic_first_order_task_factory,
    binary_factory,
    ternary_factory,
    quaternary_factory,  # 新增
)

from .operators import (
    # 基础算子
    basic_ops,
    ts_ops,
    group_ops,
    VEC_OPS,
    vec_ops,
    extended_ops,
    # 工厂函数
    ts_factory,
    group_factory,
    first_order_factory,
    second_order_factory,  # 新增: 二阶group工厂
)

from .fields import (
    FieldSpec,
    SampleSpec,
    preprocess_field,
    sample_field_specs,
    sample_scalar_expressions,
)

from .local_fields import (
    read_local_field_rows,
    load_local_field_specs,
)

from .semantic_pairs import (
    find_positive_negative_pairs,
    find_cap_pairs,
    semantic_pair_task_factory,
)

from .paired_bases import (
    PairSpec,
    parse_pair_spec,
    parse_pair_specs,
    discover_pair_specs,
    paired_field_ids,
    paired_base_task_factory,
    paired_unary_task_factory,
    paired_first_order_task_factory,
    paired_group_first_order_task_factory,
)

from .density import (
    SignalGate,
    DensityRow,
    compute_density,
    top_templates,
)

from .ai_workflow import (
    SurveyConfig,
    DeepenConfig,
    SignalBranchConfig,
    OptimizeConfig,
    WorkflowResult,
    build_signal_branches,
    run_signal_branches,
    run_survey_with_fields,
    run_full_workflow,
    filter_alphas_for_optimization,
    filter_high_quality_alphas,
    filter_marginal_alphas,
    filter_ready_for_submission,
)

from .optimize import (
    AlphaFilter,
    OptimizeConfig as OptimizeFilterConfig,
    filter_alphas,
    filter_by_ids,
    filter_by_quality,
    filter_marginal,
    filter_for_submission,
    summarize_filtered,
)

from .database import (
    AlphaDatabase,
    AlphaExpression,
    AlphaDetail,
)

from .pruning import (
    # 工具
    classify_field,
    extract_field_ids,
    # 1. 语义剪枝
    SemanticPruneConfig,
    semantic_prune_fields,
    # 2. 同字段 top-k
    FieldTopKConfig,
    field_topk_prune,
    # 3. 相关性剪枝
    CorrelationPruneConfig,
    correlation_prune,
    # 4. 本地 SC/PC 预检
    LocalCheckConfig,
    compute_self_correlation,
    local_sc_precheck,
)

from .evaluation import (
    # 常量
    RA_CHECK_NAMES,
    PPA_CHECK_NAMES,
    PASS_STATES,
    # Failed Gate 计数
    FailedGateResult,
    count_failed_gates,
    # 数据集质量
    DatasetQuality,
    evaluate_dataset_quality,
    # Alpha 评价
    AlphaEvaluation,
    evaluate_alpha,
    # 数据包解析
    extract_datapack_stats,
    filter_datasets_by_datapack,
    filter_fields_by_datapack,
)

__all__ = [
    # Families
    "UNARY_TEMPLATES",
    "BINARY_TEMPLATES",
    "TERNARY_TEMPLATES",
    "QUATERNARY_TEMPLATES",
    "Task",
    "unary_factory",
    "first_order_task_factory",
    "binary_factory",
    "ternary_factory",
    "quaternary_factory",
    # Operators
    "basic_ops",
    "ts_ops",
    "group_ops",
    "VEC_OPS",
    "vec_ops",
    "extended_ops",
    "ts_factory",
    "group_factory",
    "first_order_factory",
    "second_order_factory",
    # Fields
    "FieldSpec",
    "SampleSpec",
    "preprocess_field",
    "sample_field_specs",
    "sample_scalar_expressions",
    "read_local_field_rows",
    "load_local_field_specs",
    "find_positive_negative_pairs",
    "find_cap_pairs",
    "semantic_pair_task_factory",
    "PairSpec",
    "parse_pair_spec",
    "parse_pair_specs",
    "discover_pair_specs",
    "paired_field_ids",
    "paired_base_task_factory",
    "paired_unary_task_factory",
    "paired_first_order_task_factory",
    "paired_group_first_order_task_factory",
    # Density
    "SignalGate",
    "DensityRow",
    "compute_density",
    "top_templates",
    # AI Workflow
    "SurveyConfig",
    "DeepenConfig",
    "SignalBranchConfig",
    "OptimizeConfig",
    "WorkflowResult",
    "build_signal_branches",
    "run_signal_branches",
    "run_survey_with_fields",
    "run_full_workflow",
    # Alpha Filtering
    "AlphaFilter",
    "OptimizeFilterConfig",
    "filter_alphas",
    "filter_by_ids",
    "filter_by_quality",
    "filter_marginal",
    "filter_for_submission",
    "filter_alphas_for_optimization",
    "filter_high_quality_alphas",
    "filter_marginal_alphas",
    "filter_ready_for_submission",
    "summarize_filtered",
    # Alpha Source
    "get_alphas_from_workflow_result",
    "load_alphas_from_file",
    "fetch_user_alphas",
    "fetch_alpha_by_ids",
    "get_and_filter_alphas",
    # Database
    "AlphaDatabase",
    "AlphaExpression",
    "AlphaDetail",
    # Pruning
    "classify_field",
    "extract_field_ids",
    "SemanticPruneConfig",
    "semantic_prune_fields",
    "FieldTopKConfig",
    "field_topk_prune",
    "CorrelationPruneConfig",
    "correlation_prune",
    "LocalCheckConfig",
    "compute_self_correlation",
    "local_sc_precheck",
    # Evaluation
    "RA_CHECK_NAMES",
    "PPA_CHECK_NAMES",
    "PASS_STATES",
    "FailedGateResult",
    "count_failed_gates",
    "DatasetQuality",
    "evaluate_dataset_quality",
    "AlphaEvaluation",
    "evaluate_alpha",
    "extract_datapack_stats",
    "filter_datasets_by_datapack",
    "filter_fields_by_datapack",
]
