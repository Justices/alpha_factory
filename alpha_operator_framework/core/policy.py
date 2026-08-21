"""事件溯源研究内核 — 研究策略规范 (Research Policy Specification).

定义可重放、可 A/B 对比的不可变研究策略，涵盖预算分配、时间分区、选择规则与停止条件。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ValidationPartitions:
    """时间分区策略 (严格隔离 IS、验证集与 Locked OOS)."""

    discovery_is: List[str] = field(default_factory=lambda: ["2016-01-01", "2021-12-31"])
    validation: List[str] = field(default_factory=lambda: ["2022-01-01", "2023-12-31"])
    locked_oos: List[str] = field(default_factory=lambda: ["2024-01-01", "2025-12-31"])


@dataclass(frozen=True)
class BudgetPolicy:
    """计算与平台回测预算策略."""

    simulations_per_round: int = 100
    exploration_fraction: float = 0.6    # 探索新模板/新字段
    exploitation_fraction: float = 0.3   # 正向信号变异微调
    novelty_fraction: float = 0.1        # 纯另类新颖数据挖掘


@dataclass(frozen=True)
class SelectionPolicy:
    """因子族选择与晋级策略."""

    unit: str = "factor_family"          # 以因子族为竞争单元
    max_structural_neighbors: int = 3    # 同结构族最大代表数
    min_oos_sharpe: float = 1.25
    min_fitness: float = 1.0
    max_turnover: float = 0.70
    max_correlation: float = 0.70


@dataclass(frozen=True)
class StopPolicy:
    """研究族停止规则 (防止无节制数据挖掘)."""

    min_trials_per_family: int = 30
    stop_if_posterior_hit_rate_below: float = 0.02  # 胜率低于 2% 触发永久停止


@dataclass(frozen=True)
class ResearchPolicy:
    """不可变研究策略实体 (Research Policy)."""

    policy_id: str
    version: str = "1.0.0"
    objective: str = "discover_low_correlation_alphas"
    region: str = "GBR"
    universe: str = "TOP700"
    delay: int = 1
    datasets: List[str] = field(default_factory=lambda: ["insider_agg_matrix", "pattern_scores", "fundamental31"])
    validation: ValidationPartitions = field(default_factory=ValidationPartitions)
    budget: BudgetPolicy = field(default_factory=BudgetPolicy)
    selection: SelectionPolicy = field(default_factory=SelectionPolicy)
    stopping: StopPolicy = field(default_factory=StopPolicy)

    def compute_policy_hash(self) -> str:
        """计算策略不可变指纹 (SHA256)."""
        d = asdict(self)
        raw = json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def should_stop_family(self, family_trials: int, successful_count: int) -> bool:
        """根据贝叶斯后验胜率判定当前因子族是否应触发停止剪枝."""
        if family_trials < self.stopping.min_trials_per_family:
            return False
        # Laplace 平滑后验胜率
        posterior_hit_rate = (successful_count + 1) / (family_trials + 2)
        return posterior_hit_rate < self.stopping.stop_if_posterior_hit_rate_below

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResearchPolicy:
        d = dict(data)
        if "validation" in d and isinstance(d["validation"], dict):
            d["validation"] = ValidationPartitions(**d["validation"])
        if "budget" in d and isinstance(d["budget"], dict):
            d["budget"] = BudgetPolicy(**d["budget"])
        if "selection" in d and isinstance(d["selection"], dict):
            d["selection"] = SelectionPolicy(**d["selection"])
        if "stopping" in d and isinstance(d["stopping"], dict):
            d["stopping"] = StopPolicy(**d["stopping"])
        return cls(**d)
