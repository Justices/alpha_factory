"""Selection and pruning feedback loop tests."""

from __future__ import annotations

from alpha_operator_framework.ddd.domain import candidate_exploration as exploration
from alpha_operator_framework.ddd.domain.candidate_exploration.models import (
    Budget,
    Candidate,
    ResearchPolicy,
    SamplingWeights,
)
from alpha_operator_framework.ddd.domain.candidate_exploration.policies import WeightedStratifiedSelectionPolicy
from alpha_operator_framework.ddd.domain.experiment_governance.models import PostPruneDecision
from alpha_operator_framework.ddd.domain.knowledge_and_submission.services import SelectionFeedbackBuilder
from alpha_operator_framework.ddd.domain.ports import DeterministicRandomSource


def test_weighted_selection_prefers_field_operator_and_template_evidence() -> None:
    knowledge_type = getattr(exploration, "SelectionKnowledgeSnapshot", None)
    assert knowledge_type is not None
    knowledge = knowledge_type(
        version=3,
        field_stats={"good_field": {"score": 2.0}, "weak_field": {"score": -2.0}},
        operator_stats={"rank": {"score": 1.0}, "ts_rank": {"score": -1.0}},
        template_stats={"good_template": {"score": 1.0}, "weak_template": {"score": -1.0}},
    )
    candidates = [
        Candidate(
            candidate_id="weak",
            expression="ts_rank(weak_field, 5)",
            family="family",
            fields=["weak_field"],
            operators=["ts_rank"],
            template_id="weak_template",
        ),
        Candidate(
            candidate_id="strong",
            expression="rank(good_field)",
            family="family",
            fields=["good_field"],
            operators=["rank"],
            template_id="good_template",
        ),
    ]
    policy = ResearchPolicy(
        budget=Budget(max_backtested=1),
        weights=SamplingWeights(field=1.0, operator=1.0, template=1.0, novelty=0.0, uncertainty=0.0),
    )

    decisions = WeightedStratifiedSelectionPolicy().select(
        candidates, policy, DeterministicRandomSource(7), knowledge
    )

    assert [d.candidate_id for d in decisions if d.is_selected] == ["strong"]
    assert decisions[1].score_components["field"] > decisions[0].score_components["field"]


def test_prune_rule_excludes_candidate_from_weighted_selection() -> None:
    knowledge_type = getattr(exploration, "SelectionKnowledgeSnapshot", None)
    assert knowledge_type is not None
    knowledge = knowledge_type(version=4, prune_rules=("blocked_template",))
    candidate = Candidate(
        candidate_id="blocked",
        expression="rank(field)",
        family="family",
        fields=["field"],
        operators=["rank"],
        template_id="blocked_template",
    )
    policy = ResearchPolicy(budget=Budget(max_backtested=1))

    decisions = WeightedStratifiedSelectionPolicy().select(
        [candidate], policy, DeterministicRandomSource(7), knowledge
    )

    assert decisions[0].is_selected is False
    assert decisions[0].reason == "Rejected by distilled prune rule"


def test_pruned_template_is_returned_as_selection_feedback() -> None:
    feedback = SelectionFeedbackBuilder().build_feedback(
        results=[],
        distilled_templates=[],
        post_prunes=[
            PostPruneDecision(
                task_id="task",
                is_pruned=True,
                reason_code="EXTREME_NOISE_OR_TURNOVER",
                evidence={"template_id": "noisy_template"},
            )
        ],
    )

    assert [rule.pattern for rule in feedback.new_prune_rules] == ["noisy_template"]
