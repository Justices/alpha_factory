"""Compatibility facade for the carpet-mining package."""

from __future__ import annotations

from typing import Optional, Sequence

from alpha_operator_framework.carpet import (
    CarpetMiningConfig,
    CarpetMiningResult,
    StratifiedCarpetMiner,
)
from alpha_operator_framework.carpet.miner import _run_stratified_carpet_mining_with
from alpha_operator_framework.domain.families import Task as Task


def run_stratified_carpet_mining(
    region: str = "GBR",
    universe: str = "TOP700",
    datasets: Optional[Sequence[str]] = None,
    sample_per_family: int = 4,
    batch_size: int = 5,
    delay: int = 1,
    decay: int = 12,
    neutralization: str = "SUBINDUSTRY",
    truncation: float = 0.08,
    execute: bool = True,
    seed: Optional[int] = None,
    output_report_path: Optional[str] = None,
) -> CarpetMiningResult:
    """Run carpet mining through the legacy, patchable miner seam."""
    return _run_stratified_carpet_mining_with(
        StratifiedCarpetMiner,
        region=region,
        universe=universe,
        datasets=datasets,
        sample_per_family=sample_per_family,
        batch_size=batch_size,
        delay=delay,
        decay=decay,
        neutralization=neutralization,
        truncation=truncation,
        execute=execute,
        seed=seed,
        output_report_path=output_report_path,
    )

__all__ = [
    "CarpetMiningConfig",
    "CarpetMiningResult",
    "StratifiedCarpetMiner",
    "run_stratified_carpet_mining",
]
