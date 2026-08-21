"""蒸馏层 — 研究闭环的第6步 (沉淀与抽象), 把回测经验回流到字段选择与表达式合成.

- field_signals: 字段级信号统计 (第6步 → 第1步字段选择回流)
- template_abstractor: 模板骨架抽象 (第6步 → 第2步表达式合成回流, 正向沉淀好模板)
- template_pruner: 模板蒸馏淘汰 (第6步 → 第2步, 负向淘汰零信号坏模板)
- pair_signals: 配对级信号统计 (第6步 → 第2步配对选择回流)
- operator_signals: 算子级信号统计与证据驱动挑选 (第6步 → 第2步算子选择回流)
"""

from .field_signals import (
    FieldSignalStat,
    aggregate_field_signals,
    weighted_field_sample,
)
from .template_abstractor import (
    TemplateAbstraction,
    abstract_template,
    abstract_templates,
    to_template,
    distill_templates_into_library,
)
from .template_pruner import (
    deactivate_noisy_templates,
    prune_templates_by_density,
    DEFAULT_PRUNE_RULES,
    matches_prune_rule,
    prune_expression_candidates,
    seed_default_prune_rules,
    distill_prune_rules_from_density,
)
from .pair_signals import (
    PairSignalStat,
    aggregate_pair_signals,
)
from .operator_signals import (
    OperatorSignalStat,
    extract_operators,
    aggregate_operator_signals,
    select_curated_operators,
)
from .diagnostic import (
    FailureMode,
    FailureDiagnosis,
    diagnose_alpha_failure,
)
from .mutation import (
    AlphaMutator,
    auto_repair_failed_alphas,
)

__all__ = [
    "FieldSignalStat",
    "aggregate_field_signals",
    "weighted_field_sample",
    "TemplateAbstraction",
    "abstract_template",
    "abstract_templates",
    "to_template",
    "distill_templates_into_library",
    "deactivate_noisy_templates",
    "prune_templates_by_density",
    "DEFAULT_PRUNE_RULES",
    "matches_prune_rule",
    "prune_expression_candidates",
    "seed_default_prune_rules",
    "distill_prune_rules_from_density",
    "PairSignalStat",
    "aggregate_pair_signals",
    "OperatorSignalStat",
    "extract_operators",
    "aggregate_operator_signals",
    "select_curated_operators",
    "FailureMode",
    "FailureDiagnosis",
    "diagnose_alpha_failure",
    "AlphaMutator",
    "auto_repair_failed_alphas",
]


