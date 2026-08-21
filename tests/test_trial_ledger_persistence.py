"""Unit tests for TrialLedger SQLite persistence and intra-family correlation adjustments."""

import pytest
from pathlib import Path

from alpha_operator_framework.domain.overfitting import TrialLedger


def test_trial_ledger_persistence_and_recovery(tmp_path):
    """测试 TrialLedger 的持久化写入与跨实例恢复能力."""
    db_file = tmp_path / "trial_ledger.db"

    # 1. 实例 A 写入 5 条记录
    ledger_a = TrialLedger(db_path=db_file)
    for i in range(5):
        ledger_a.record_trial(f"expr_a_{i}", family="momentum")
    for i in range(3):
        ledger_a.record_trial(f"expr_b_{i}", family="reversion")

    # 2. 模拟进程重启，创建全新的实例 B 连接同一数据库
    ledger_b = TrialLedger(db_path=db_file)
    assert ledger_b._total_trials == 8
    assert ledger_b.get_effective_trials("momentum") == int(round(1.0 + 4 * 0.65))
    assert ledger_b.get_effective_trials("reversion") == int(round(1.0 + 2 * 0.65))


def test_trial_ledger_intra_family_correlation_decay():
    """测试结构族内相关性对有效试验次数的统计折损模型."""
    ledger = TrialLedger()

    # 在同一模板族内执行 100 次试验
    for i in range(100):
        ledger.record_trial(f"ts_rank_expr_{i}", family="time_series")

    # 若完全独立 (rho = 0.0), N_eff = 100
    n_eff_indep = ledger.get_effective_trials("time_series", intra_family_correlation=0.0)
    assert n_eff_indep == 100

    # 若中度相关 (rho = 0.35), N_eff = 1 + 99 * 0.65 = 65
    n_eff_med = ledger.get_effective_trials("time_series", intra_family_correlation=0.35)
    assert n_eff_med == 65

    # 若高度相关 (rho = 0.80), N_eff = 1 + 99 * 0.20 = 21
    n_eff_high = ledger.get_effective_trials("time_series", intra_family_correlation=0.80)
    assert n_eff_high == 21
