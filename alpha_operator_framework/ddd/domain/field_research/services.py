"""Field Research Bounded Context - Domain Services."""

from __future__ import annotations

import math
from typing import Dict, List, Sequence
from .models import FieldProfile, FieldSnapshot, FieldUniverse


class FieldEligibilityService:
    """Evaluates whether a field satisfies basic quality and data health requirements."""

    def __init__(self, min_coverage: float = 0.70, max_crowding_alphas: int = 10000):
        self.min_coverage = min_coverage
        self.max_crowding_alphas = max_crowding_alphas

    def evaluate_eligibility(self, snapshot: FieldSnapshot) -> tuple[bool, str]:
        if snapshot.coverage < self.min_coverage:
            return False, f"Coverage {snapshot.coverage:.2%} < threshold {self.min_coverage:.2%}"
        if snapshot.alpha_count > self.max_crowding_alphas:
            return False, f"Extreme crowding: {snapshot.alpha_count} platform alphas"
        return True, "PASS"


class FieldProfiler:
    """Computes field novelty, crowding, and initial sampling weights."""

    def profile_fields(
        self,
        universe: FieldUniverse,
        eligibility_service: FieldEligibilityService,
    ) -> None:
        for fid, snap in universe.snapshots.items():
            is_elig, reason = eligibility_service.evaluate_eligibility(snap)
            
            # Crowding score in [0.0, 1.0]
            crowding = min(1.0, math.log1p(snap.alpha_count + snap.user_count * 2) / 10.0)
            
            profile = universe.profiles.get(fid) or FieldProfile(field_id=fid, dataset_id=snap.dataset_id)
            profile.is_eligible = is_elig
            profile.eligibility_reason = reason
            profile.coverage = snap.coverage
            profile.crowding_score = crowding
            
            # Base sampling weight: high novelty + low crowding + high coverage
            if is_elig:
                profile.sampling_weight = max(0.1, (1.0 - crowding * 0.5) * profile.novelty_score * snap.coverage)
            else:
                profile.sampling_weight = 0.0

            universe.update_profile(profile)


class FieldWeightUpdater:
    """Updates field weights based on feedback from completed backtest batches."""

    def apply_feedback(
        self,
        universe: FieldUniverse,
        field_performance: Dict[str, Dict[str, float]],
    ) -> None:
        """
        field_performance: {field_id: {'avg_sharpe': float, 'test_count': int, 'is_noise': bool, 'is_alpha': bool}}
        """
        for fid, metrics in field_performance.items():
            if fid not in universe.profiles:
                continue
            prof = universe.profiles[fid]
            prof.historical_tests += int(metrics.get("test_count", 0))
            prof.historical_avg_sharpe = metrics.get("avg_sharpe", 0.0)
            
            if metrics.get("is_alpha", False):
                prof.tier = "Alpha"
                prof.sampling_weight = min(5.0, prof.sampling_weight * 1.5)
            elif metrics.get("is_noise", False):
                prof.tier = "Noise"
                prof.sampling_weight = max(0.05, prof.sampling_weight * 0.4)
            else:
                prof.tier = "Neutral"

            universe.update_profile(prof)
