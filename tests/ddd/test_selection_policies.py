"""Unit tests for all 4 Selection Policies and Deterministic Reproducibility."""

import pytest
from alpha_operator_framework.ddd.domain.ports import DeterministicRandomSource
from alpha_operator_framework.ddd.domain.candidate_exploration.models import (
    Budget,
    Candidate,
    ResearchPolicy,
)
from alpha_operator_framework.ddd.domain.candidate_exploration.policies import (
    DOptimalDiversitySelectionPolicy,
    NSGA2CandidateEvolutionPolicy,
    ThompsonCombinatorialSelectionPolicy,
    UCBCombinatorialSelectionPolicy,
    WeightedStratifiedSelectionPolicy,
)


@pytest.fixture
def sample_candidates():
    cands = []
    families = ["ts_momentum", "reversion", "group_neutral", "three_tier_standard"]
    for i in range(20):
        fam = families[i % len(families)]
        cands.append(
            Candidate(
                candidate_id=f"c_{i:02d}",
                expression=f"rank(field_{i:02d})",
                family=fam,
                fields=[f"field_{i:02d}"],
            )
        )
    return cands


def test_stratified_selection_deterministic(sample_candidates):
    policy = ResearchPolicy(budget=Budget(max_backtested=8))
    strat = WeightedStratifiedSelectionPolicy()

    rng1 = DeterministicRandomSource(42)
    decisions1 = strat.select(sample_candidates, policy, rng1)
    sel1 = [d.candidate_id for d in decisions1 if d.is_selected]

    rng2 = DeterministicRandomSource(42)
    decisions2 = strat.select(sample_candidates, policy, rng2)
    sel2 = [d.candidate_id for d in decisions2 if d.is_selected]

    assert len(sel1) == 8
    assert sel1 == sel2  # 100% deterministic reproducibility


def test_d_optimal_diversity_selection(sample_candidates):
    policy = ResearchPolicy(budget=Budget(max_backtested=6))
    d_opt = DOptimalDiversitySelectionPolicy()
    rng = DeterministicRandomSource(42)

    decisions = d_opt.select(sample_candidates, policy, rng)
    selected = [sample_candidates[int(d.candidate_id.split('_')[1])] for d in decisions if d.is_selected]

    # Verify high diversity across families and fields
    selected_fams = {c.family for c in selected}
    assert len(selected_fams) == 4
    assert len(selected) == 6


def test_thompson_and_ucb_combinatorial_selection(sample_candidates):
    policy = ResearchPolicy(budget=Budget(max_backtested=5))
    knowledge = {
        "ts_momentum": {"trials": 10, "avg_sharpe": 1.4, "successes": 8, "failures": 2},
        "reversion": {"trials": 10, "avg_sharpe": -0.2, "successes": 1, "failures": 9},
    }

    # Thompson
    thomp = ThompsonCombinatorialSelectionPolicy()
    th_decisions = thomp.select(sample_candidates, policy, DeterministicRandomSource(42), context_knowledge=knowledge)
    th_sel = [d.candidate_id for d in th_decisions if d.is_selected]
    assert len(th_sel) == 5

    # UCB
    ucb = UCBCombinatorialSelectionPolicy()
    ucb_decisions = ucb.select(sample_candidates, policy, DeterministicRandomSource(42), context_knowledge=knowledge)
    ucb_sel = [d.candidate_id for d in ucb_decisions if d.is_selected]
    assert len(ucb_sel) == 5


def test_nsga2_pareto_evolution_policy(sample_candidates):
    policy = ResearchPolicy(budget=Budget(max_backtested=4))
    nsga2 = NSGA2CandidateEvolutionPolicy()
    decisions = nsga2.select(sample_candidates, policy, DeterministicRandomSource(42))
    sel = [d for d in decisions if d.is_selected]
    assert len(sel) == 4
    assert all(d.algorithm == "nsga2_pareto" for d in sel)
