"""Typed records for the SQLite research tables."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AlphaExpression:
    id: Optional[int] = None
    expression_sha: str = ""
    expression: str = ""
    expression_origin: str = ""
    settings: str = ""
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
    sc_result: str = ""
    sc_value: Optional[float] = None
    pc_result: str = ""
    pc_value: Optional[float] = None
    checks_json: str = ""
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
