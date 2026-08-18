"""蒸馏层 — 研究闭环的第6步 (沉淀与抽象), 把回测经验回流到字段选择与表达式合成.

- field_signals: 字段级信号统计 (第6步 → 第1步字段选择回流)
- template_abstractor: 模板骨架抽象 (第6步 → 第2步表达式合成回流)
- pair_signals: 配对级信号统计 (第6步 → 第2步配对选择回流)
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
from .pair_signals import (
    PairSignalStat,
    aggregate_pair_signals,
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
    "PairSignalStat",
    "aggregate_pair_signals",
]
