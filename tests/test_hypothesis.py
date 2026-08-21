"""Unit tests for Hypothesis-Driven Alpha Reasoning Engine."""

import pytest

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.generation.hypothesis import (
    BUILTIN_HYPOTHESES,
    EconomicHypothesis,
    HypothesisCategory,
    HypothesisEngine,
)


def test_builtin_hypotheses_catalog():
    assert len(BUILTIN_HYPOTHESES) >= 5
    categories = {h.category for h in BUILTIN_HYPOTHESES}
    assert HypothesisCategory.ANALYST_DISPERSION in categories
    assert HypothesisCategory.LIQUIDITY_VOLATILITY in categories
    assert HypothesisCategory.QUALITY_VALUE in categories
    assert HypothesisCategory.MOMENTUM_REVERSAL in categories


def test_instantiate_hypothesis():
    engine = HypothesisEngine()
    hyp = BUILTIN_HYPOTHESES[0]  # hyp_analyst_revision_momentum

    slots = {"a": "est_eps_up", "b": "est_eps_num"}
    tasks = engine.instantiate_hypothesis(hyp, slots, decay=5.0)

    assert len(tasks) > 0
    for t in tasks:
        assert t.family == "hypothesis"
        assert t.meta["hypothesis_id"] == hyp.id
        assert "est_eps_up" in t.expression or "est_eps_num" in t.expression
        assert t.decay == 5.0


def test_generate_tasks_for_all_hypotheses():
    engine = HypothesisEngine()
    fields = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", category="price"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", category="volume"),
        FieldSpec(id="est_eps_up", dataset_id="analyst1", type="MATRIX", category="analyst"),
        FieldSpec(id="est_eps_total", dataset_id="analyst1", type="MATRIX", category="analyst"),
        FieldSpec(id="operating_cashflow", dataset_id="fund1", type="MATRIX", category="fundamental"),
        FieldSpec(id="net_income", dataset_id="fund1", type="MATRIX", category="fundamental"),
    ]

    tasks = engine.generate_tasks_for_all_hypotheses(fields, max_tasks_per_hypothesis=3)
    assert len(tasks) >= 5

    # Check provenance origin
    origins = {t.expression_origin for t in tasks}
    assert any("hyp_" in o for o in origins)


def test_build_llm_prompt():
    engine = HypothesisEngine()
    fields = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", description="Daily close price"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", description="Daily volume"),
    ]
    prompt = engine.build_llm_prompt("USA", "TOP3000", fields)
    assert "USA" in prompt
    assert "TOP3000" in prompt
    assert "close" in prompt
    assert "JSON" in prompt
