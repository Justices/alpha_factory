"""WorldQuant BRAIN 真实平台生产适配器 (Real Platform Production Adapter).

桥接 BrainPlatformSimulator、Outbox Worker 与事件溯源研究引擎，将平台原始响应转换为标准化的
证据可信度载体 (Evidence Carrier) 与指标字典。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from alpha_operator_framework.domain.evidence import EvidenceLevel
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.platform.platform_simulator import (
    DEFAULT_BASE_URL,
    BrainPlatformSimulator,
    PlatformAlphaResult,
)
from cnhkmcp.session_manager import BrainSessionManager

logger = logging.getLogger(__name__)


class BrainPlatformAdapter:
    """WorldQuant BRAIN 真实平台生产适配器."""

    def __init__(
        self,
        simulator: Optional[BrainPlatformSimulator] = None,
        session_manager: Optional[BrainSessionManager] = None,
        base_url: str = DEFAULT_BASE_URL,
    ):
        self.simulator = simulator or BrainPlatformSimulator(
            session_manager=session_manager,
            base_url=base_url,
        )

    def simulate_single(self, expression: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """单任务仿真接口 (供 Outbox Worker 与 EventSourcedResearchEngine 调用)."""
        results = self.simulate_batch([{"expression": expression}], settings, batch_size=1)
        if results:
            return results[0]
        return {
            "alpha_id": "FAILED_SUBMISSION",
            "expression": expression,
            "sharpe": 0.0,
            "fitness": 0.0,
            "turnover": 0.0,
            "margin": 0.0,
            "returns": 0.0,
            "drawdown": 0.0,
            "pnl": 0.0,
            "checks": [],
            "evidence_level": EvidenceLevel.SYNTHETIC.value,
            "is_valid": False,
            "error": "No result returned from platform simulator",
        }

    def simulate_batch(
        self,
        tasks: Sequence[Union[Task, Dict[str, Any]]],
        settings: Dict[str, Any],
        batch_size: int = 5,
        max_wait_seconds: float = 600.0,
    ) -> List[Dict[str, Any]]:
        """批量仿真接口 (按 batch_size 切分 chunk 真实提交平台并轮询)."""
        region = settings.get("region", "GBR")
        universe = settings.get("universe", "TOP700" if region == "GBR" else "TOP1200")
        neutralization = settings.get("neutralization", "SUBINDUSTRY")
        delay = int(settings.get("delay", 1))
        decay = int(settings.get("decay", 8))

        platform_results: List[PlatformAlphaResult] = self.simulator.run_simulations(
            tasks=tasks,
            region=region,
            universe=universe,
            neutralization=neutralization,
            delay=delay,
            decay=decay,
            batch_size=batch_size,
            max_wait_seconds=max_wait_seconds,
        )

        formatted_results: List[Dict[str, Any]] = []
        for res in platform_results:
            aid = res.alpha_id
            is_valid_alpha = bool(aid and not aid.startswith("FAILED_") and not aid.startswith("MOCK_"))

            checks_dicts = []
            if res.raw_details:
                checks_list = res.raw_details.get("is", {}).get("checks", [])
                for c in checks_list:
                    checks_dicts.append({
                        "name": c.get("name"),
                        "result": c.get("result"),
                        "value": c.get("value"),
                        "limit": c.get("limit"),
                    })

            # 真实平台回测结果赋予 PLATFORM_IS，失败或非法项降级为 SYNTHETIC
            evidence_lvl = EvidenceLevel.PLATFORM_IS.value if is_valid_alpha else EvidenceLevel.SYNTHETIC.value

            formatted_results.append({
                "alpha_id": aid,
                "expression": res.expression,
                "sharpe": float(res.sharpe),
                "fitness": float(res.fitness),
                "turnover": float(res.turnover),
                "margin": float(res.margin),
                "returns": float(res.annualized_return),
                "drawdown": float(res.max_drawdown),
                "pnl": float(res.pnl),
                "checks": checks_dicts,
                "sc_value": float(res.sc_value),
                "pc_value": float(res.pc_value),
                "evidence_level": evidence_lvl,
                "is_valid": res.is_valid,
                "failed_checks": res.failed_checks,
                "raw_details": res.raw_details,
            })

        return formatted_results
