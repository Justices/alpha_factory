"""Unit tests for Alpha Decay Profiler."""

import numpy as np
import pytest

from alpha_operator_framework.domain.decay import (
    AlphaDecayProfile,
    DecaySpeed,
    profile_alpha_decay,
)


def test_profile_alpha_decay_fast_signal():
    rng = np.random.default_rng(42)
    T = 100
    N = 30

    # 构造快速衰减信号: lag 1 有强相关, lag 3 迅速衰减至 0
    returns = rng.normal(0, 0.02, size=(T, N))
    signal = np.zeros((T, N))
    for t in range(T - 1):
        signal[t] = returns[t + 1] + rng.normal(0, 0.005, size=N)

    profile = profile_alpha_decay(signal, returns, max_lag=10)

    assert len(profile.ic_curve) == 10
    assert profile.initial_ic > 0.50  # Strong 1-day IC
    assert profile.decay_speed in (DecaySpeed.ULTRA_FAST, DecaySpeed.FAST)
    assert 1 <= profile.recommended_decay <= 6


def test_profile_alpha_decay_persistent_signal():
    rng = np.random.default_rng(42)
    T = 120
    N = 30

    # 构造慢速持续信号: 信号预测未来 10 天的均值
    returns = rng.normal(0, 0.01, size=(T, N))
    signal = np.zeros((T, N))
    for t in range(T - 15):
        forward_avg = np.mean(returns[t + 1 : t + 15], axis=0)
        signal[t] = forward_avg + rng.normal(0, 0.002, size=N)

    profile = profile_alpha_decay(signal, returns, max_lag=15)

    assert profile.initial_ic > 0.10
    assert profile.half_life >= 5.0
    assert profile.recommended_decay >= 6
    assert profile.decay_speed in (DecaySpeed.MODERATE, DecaySpeed.PERSISTENT, DecaySpeed.SLOW)
