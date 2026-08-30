
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy
from alpha_operator_framework.research.selection_report import compare_selection_strategies


def test_selection_report_is_replayable_for_same_seed() -> None:
    policy = ResearchPolicy("GBR", "TOP700", 1, policy_version="p2")
    candidates = [
        Candidate("a", "rank(close)", "f", ("close",), ("rank",), "t"),
        Candidate("b", "rank(open)", "f", ("open",), ("rank",), "t"),
    ]

    first = compare_selection_strategies(candidates, policy, KnowledgeSnapshot(version=0), seed=7, strategies=("weighted_stratified", "ucb"))
    second = compare_selection_strategies(candidates, policy, KnowledgeSnapshot(version=0), seed=7, strategies=("weighted_stratified", "ucb"))

    assert first == second
    assert first["weighted_stratified"]["policy_version"] == "p2"
