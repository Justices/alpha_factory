from __future__ import annotations

import inspect

from alpha_operator_framework.carpet import (
    CarpetMiningConfig as NewConfig,
    CarpetMiningResult as NewResult,
    StratifiedCarpetMiner as NewMiner,
    run_stratified_carpet_mining as new_run,
)
from alpha_operator_framework.carpet_mining import (
    CarpetMiningConfig as OldConfig,
    CarpetMiningResult as OldResult,
    StratifiedCarpetMiner as OldMiner,
    run_stratified_carpet_mining as old_run,
)


def test_legacy_carpet_imports_are_exact_new_package_exports() -> None:
    assert OldConfig is NewConfig
    assert OldResult is NewResult
    assert OldMiner is NewMiner
    assert inspect.signature(old_run) == inspect.signature(new_run)


def test_legacy_runner_uses_the_facade_miner_patch_seam(monkeypatch) -> None:
    import alpha_operator_framework.carpet_mining as legacy

    sentinel = object()
    seen = []

    class FakeMiner:
        def __init__(self, config):
            seen.append(config)

        def run(self):
            return sentinel

    monkeypatch.setattr(legacy, "StratifiedCarpetMiner", FakeMiner)

    result = legacy.run_stratified_carpet_mining(
        datasets=["offline"],
        execute=False,
        seed=17,
    )

    assert result is sentinel
    assert seen[0].datasets == ["offline"]
    assert seen[0].execute is False
    assert seen[0].seed == 17


def test_dry_run_stage_services_return_no_platform_results() -> None:
    miner = NewMiner.__new__(NewMiner)
    miner.config = NewConfig(execute=False, optimize_signals=True)

    assert miner.run_batch_simulation_and_persist([]) == []
    assert miner.optimize_positive_signals([]) == []


def test_carpet_package_exposes_only_the_stable_public_api() -> None:
    import alpha_operator_framework.carpet as carpet

    assert carpet.__all__ == [
        "CarpetMiningConfig",
        "CarpetMiningResult",
        "StratifiedCarpetMiner",
        "run_stratified_carpet_mining",
    ]
