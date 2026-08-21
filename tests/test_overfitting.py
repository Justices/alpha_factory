"""Unit tests for statistical overfitting defense (PSR, DSR, Haircut Sharpe, PBO/CSCV)."""

import numpy as np
import pytest

from alpha_operator_framework.domain.overfitting import (
    compute_dsr,
    compute_expected_max_sharpe,
    compute_haircut_sharpe,
    compute_pbo_cscv,
    compute_psr,
)


def test_compute_psr():
    # 1. Zero Sharpe against 0 benchmark should give ~0.50 (50% probability)
    psr_zero = compute_psr(sharpe=0.0, t_days=252, benchmark_sharpe=0.0)
    assert abs(psr_zero - 0.5) < 0.05

    # 2. High Sharpe (2.0) over 252 days should give near 1.0 probability
    psr_high = compute_psr(sharpe=2.0, t_days=252, benchmark_sharpe=0.0)
    assert psr_high > 0.99

    # 3. Negative Sharpe (-1.5) should give near 0.0 probability
    psr_neg = compute_psr(sharpe=-1.5, t_days=252, benchmark_sharpe=0.0)
    assert psr_neg < 0.01


def test_compute_expected_max_sharpe():
    # E[max_N] should increase strictly monotonically with trial count N
    e_max_10 = compute_expected_max_sharpe(trial_count=10, sharpe_std=0.5)
    e_max_100 = compute_expected_max_sharpe(trial_count=100, sharpe_std=0.5)
    e_max_1000 = compute_expected_max_sharpe(trial_count=1000, sharpe_std=0.5)

    assert 0.0 < e_max_10 < e_max_100 < e_max_1000
    assert e_max_1000 > 1.2  # 1000 random trials easily generate Sharpe > 1.2 by pure chance!


def test_compute_dsr_overfitting_penalty():
    nominal_sharpe = 1.30
    t_days = 252

    # 1. With trial_count = 1, nominal Sharpe 1.30 has high confidence
    dsr_single_trial = compute_dsr(sharpe=nominal_sharpe, trial_count=1, t_days=t_days)
    assert dsr_single_trial > 0.95

    # 2. After trial_count = 2000, nominal Sharpe 1.30 is penalized as likely overfitted noise
    dsr_multi_trials = compute_dsr(sharpe=nominal_sharpe, trial_count=2000, t_days=t_days)
    assert dsr_multi_trials < 0.80  # Fails 95% significance test!

    # 3. Very high genuine Sharpe (e.g. 2.80) should still pass DSR even after 2000 trials
    dsr_stellar = compute_dsr(sharpe=2.80, trial_count=2000, t_days=t_days)
    assert dsr_stellar > 0.95


def test_compute_haircut_sharpe():
    # Single trial -> no haircut
    assert compute_haircut_sharpe(sharpe=1.5, trial_count=1, t_days=252) == 1.5

    # Multi trials -> conservative discount
    discounted = compute_haircut_sharpe(sharpe=1.5, trial_count=1000, t_days=500)
    assert 0.0 < discounted < 1.5


def test_compute_pbo_cscv():
    rng = np.random.default_rng(42)
    T = 252  # 1 year
    M = 20   # 20 candidate alphas

    # 1. Pure random white noise returns -> PBO should be high (~0.50 or higher)
    noise_returns = rng.normal(0.0, 0.01, size=(T, M))
    pbo_noise = compute_pbo_cscv(noise_returns, n_partitions=8)
    assert 0.0 <= pbo_noise <= 1.0
    assert pbo_noise > 0.20  # High risk of overfitting on pure noise

    # 2. Strong persistent true alpha + noise -> PBO should be low
    good_returns = rng.normal(0.0, 0.01, size=(T, M))
    # Inject strong positive drift into alpha 0 across all time partitions
    good_returns[:, 0] += 0.003
    pbo_good = compute_pbo_cscv(good_returns, n_partitions=8)
    assert pbo_good < 0.25
