"""Typed records for the SQLite research tables."""

from dataclasses import dataclass, field
from typing import List, Optional


# 系统内工作流阶段 (五态): 与平台侧 status_platform/stage_platform 区分
WF_STAGES = ("pending_validation", "validated", "submitted", "failed", "needs_optimization")


@dataclass
class AlphaExpression:
    id: Optional[int] = None
    expression_sha: str = ""
    expression: str = ""
    expression_origin: str = ""
    settings: str = ""
    batch_id: Optional[int] = None   # 最近一次回测批次 id
    fields: str = "[]"               # 表达式用到的字段清单(JSON数组字符串)
    status: str = "pending"          # pending/completed/failed/pruned
    first_operator: str = ""         # 第一个操作符(用于分层抽样)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class AlphaDetail:
    id: Optional[int] = None
    alpha_id: str = ""
    expression_sha: str = ""
    alpha_sha: str = ""
    expression: str = ""
    region: str = ""
    universe: str = ""
    delay: int = 1
    decay: float = 0.0
    neutralization: str = ""
    truncation: float = 0.0
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0
    pnl: float = 0.0
    returns: float = 0.0
    drawdown: float = 0.0
    long_count: int = 0
    short_count: int = 0
    grade: str = ""
    stage_platform: str = ""
    status_platform: str = ""
    wf_stage: str = "pending_validation"  # 系统内阶段, 见 WF_STAGES; 读字段(写走专门方法)
    sc_result: str = ""
    sc_value: Optional[float] = None
    pc_result: str = ""
    pc_value: Optional[float] = None
    checks_json: str = ""
    ra_failed: int = 0      # 失败的 RA 检查项数量(参考 WebDataScope failedNumRA)
    ppa_failed: int = 0     # 失败的 PPA 检查项数量(参考 WebDataScope failedNumPPA)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class AlphaCheck:
    alpha_id: str = ""
    check_name: str = ""
    result: str = ""
    limit: Optional[float] = None
    value: Optional[float] = None
    extra_json: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SimulationBatch:
    id: Optional[int] = None
    platform_batch_id: str = ""
    platform_location: str = ""
    status: str = "created"
    settings_json: str = ""
    requested_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    progress_json: str = ""
    result_json: str = ""
    error_message: str = ""
    submitted_at: str = ""
    last_polled_at: str = ""
    completed_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SimulationResult:
    id: Optional[int] = None
    batch_id: int = 0
    sequence_no: int = 0
    expression_sha: str = ""
    alpha_sha: str = ""
    expression: str = ""
    decay: float = 0.0
    platform_child_url: str = ""
    alpha_id: str = ""
    status: str = "created"
    result_json: str = ""
    error_message: str = ""
    completed_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class OptimizationQueueItem:
    id: Optional[int] = None
    alpha_id: str = ""
    expression: str = ""
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0
    failed_checks: str = ""
    failed_ra_count: int = 0
    failed_ppa_count: int = 0
    optimization_hints: str = ""
    status: str = "pending"
    priority: int = 0
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SubmissionCandidate:
    id: Optional[int] = None
    alpha_id: str = ""
    expression: str = ""
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0
    sc_value: Optional[float] = None
    pc_value: Optional[float] = None
    local_sc: Optional[float] = None
    local_sc_grade: str = ""
    robustness_status: str = ""
    robustness_notes: str = ""
    needs_optimization: int = 0
    is_submitted: int = 0
    submitted_at: str = ""
    pyramid_category: str = ""
    pyramid_multiplier: Optional[float] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class DataField:
    """有信号的数据字段记录(仅收录被 alpha 用到的字段)."""

    field_id: str = ""
    dataset_id: str = ""
    dataset_name: str = ""
    description: str = ""
    type: str = "MATRIX"                 # MATRIX / VECTOR / GROUP / SYMBOL
    region: str = ""
    delay: int = 1
    universes: List[str] = field(default_factory=list)          # 聚合多个 universe
    coverage: float = 0.0
    user_count: int = 0
    alpha_count: int = 0
    category: str = ""                   # 平台字段分类 (analyst/pv/model/fundamental...)
    expression_shas: List[str] = field(default_factory=list)    # 使用该字段的 alpha 表达式 sha
    last_fetched_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Template:
    """模板类库记录 (对齐 knowledge_base/alpha_templates JSONL schema)."""

    id: Optional[int] = None
    name: str = ""                       # 唯一名, 如 unary_0 / kb_placeholder_xxx
    title: str = ""                      # 模板说明(中文) / rationale
    family: str = ""                     # unary/binary/ternary/quaternary/factor/community/cold/formulaic
    template_type: str = "placeholder"   # placeholder | fixed
    expression_template: str = ""        # 含 {a}/{b}/{c}/{d} 或 <name> 占位符; fixed 时是完整表达式
    template_index: int = 0              # 族内序号 (families 兼容)
    fields_per_alpha: int = 0
    expression_origin: str = ""          # unary_template / first_order / '' (与 families 一致)
    field_types: List[str] = field(default_factory=list)        # 标量槽位允许类型, 如 ["MATRIX","VECTOR"]
    categories: List[str] = field(default_factory=list)         # 平台 category id 集合; 空=ALL
    dataset_families: List[str] = field(default_factory=list)
    placeholders: dict = field(default_factory=dict)            # {槽位: {role, type, value?, allowed_types?}}
    group_slots: List[str] = field(default_factory=list)        # ["c"] 表示 {c} 取 GROUP 字段
    slot_count: int = 0
    description: str = ""
    rationale: str = ""
    example_expression: str = ""
    settings_hint: dict = field(default_factory=dict)
    field_candidates: dict = field(default_factory=dict)
    operators_used: List[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)
    active: int = 1
    created_at: str = ""
    updated_at: str = ""
