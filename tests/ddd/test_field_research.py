"""Unit tests for Field Research Bounded Context."""

import pytest
from alpha_operator_framework.ddd.domain.field_research.models import FieldProfile, FieldSnapshot, FieldUniverse
from alpha_operator_framework.ddd.domain.field_research.services import (
    FieldEligibilityService,
    FieldProfiler,
    FieldWeightUpdater,
)


def test_field_eligibility_service():
    service = FieldEligibilityService(min_coverage=0.80, max_crowding_alphas=5000)

    good_snap = FieldSnapshot(field_id="f_good", dataset_id="ds1", coverage=0.95, alpha_count=100)
    low_cov_snap = FieldSnapshot(field_id="f_low", dataset_id="ds1", coverage=0.60, alpha_count=10)
    crowded_snap = FieldSnapshot(field_id="f_crowd", dataset_id="ds1", coverage=0.99, alpha_count=15000)

    assert service.evaluate_eligibility(good_snap)[0] is True
    assert service.evaluate_eligibility(low_cov_snap)[0] is False
    assert service.evaluate_eligibility(crowded_snap)[0] is False


def test_field_profiler_and_universe_updates():
    universe = FieldUniverse(region="GBR", universe="TOP700")
    snap1 = FieldSnapshot(field_id="vol", dataset_id="pv", coverage=0.98, user_count=5, alpha_count=200)
    snap2 = FieldSnapshot(field_id="noise", dataset_id="pv", coverage=0.40, user_count=0, alpha_count=0)
    universe.register_snapshot(snap1)
    universe.register_snapshot(snap2)

    profiler = FieldProfiler()
    eligibility = FieldEligibilityService(min_coverage=0.70)
    profiler.profile_fields(universe, eligibility)

    assert universe.profiles["vol"].is_eligible is True
    assert universe.profiles["vol"].sampling_weight > 0.5
    assert universe.profiles["noise"].is_eligible is False
    assert universe.profiles["noise"].sampling_weight == 0.0


def test_field_weight_updater_feedback():
    universe = FieldUniverse(region="GBR", universe="TOP700")
    snap = FieldSnapshot(field_id="alpha_feature", dataset_id="ds1", coverage=0.95)
    universe.register_snapshot(snap)

    updater = FieldWeightUpdater()
    initial_weight = universe.profiles["alpha_feature"].sampling_weight

    updater.apply_feedback(universe, {"alpha_feature": {"test_count": 1, "avg_sharpe": 1.5, "is_alpha": True}})
    assert universe.profiles["alpha_feature"].tier == "Alpha"
    assert universe.profiles["alpha_feature"].sampling_weight > initial_weight
