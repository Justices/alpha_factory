from alpha_operator_framework.research.template_correlation import platform_correlation, structural_similarity


def test_structural_similarity_uses_expression_tokens() -> None:
    assert structural_similarity("rank(ts_mean(returns, 20))", "rank(ts_mean(returns, 20))") == 1.0
    assert structural_similarity("rank(returns)", "group_rank(vwap, sector)") < 0.70


def test_platform_correlation_uses_the_largest_absolute_fact() -> None:
    assert platform_correlation(-0.65, 0.72) == 0.72
