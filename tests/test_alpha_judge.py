"""Unit tests for Native Alpha Judge and Value-Factor Priority Evaluation System."""

import pytest

from alpha_operator_framework.domain.judge import (
    AlphaJudge,
    JudgeReport,
    JudgeVerdict,
    RubricSeverity,
    RubricStatus,
    ValueFactorDiversity,
    compute_value_factor_diversity,
    evaluate_all_rubrics,
    evaluate_economic_foundation,
    evaluate_implementation_simplicity,
    is_atom_alpha,
    project_diversity_after_submission,
)


def test_implementation_simplicity_rubric():
    # 1. 紧凑规范的表达式 -> PASS
    valid_expr = "group_neutralize(ts_rank(close, 22), industry)"
    res_valid = evaluate_implementation_simplicity(valid_expr)
    assert res_valid.status == RubricStatus.PASS

    # 2. 算子过度堆叠 -> FAIL
    heavy_expr = "rank(" * 22 + "close" + ")" * 22
    res_heavy = evaluate_implementation_simplicity(heavy_expr, max_operators=20)
    assert res_heavy.status == RubricStatus.FAIL
    assert "算子堆叠过多" in res_heavy.reason

    # 3. 非规范时序窗口 (如 7, 13) -> WARN (INFO)
    non_canonical_expr = "ts_delta(close, 17) + ts_mean(volume, 33)"
    res_non_canon = evaluate_implementation_simplicity(non_canonical_expr)
    assert res_non_canon.status == RubricStatus.WARN
    assert "非标准周期窗口" in res_non_canon.reason


def test_economic_foundation_rubric():
    # 1. 具备清晰 rationale -> PASS
    details_good = {"rationale": "基于分析师预期修正加速产生 PEAD 盈余公告后漂移"}
    res_good = evaluate_economic_foundation(details_good)
    assert res_good.status == RubricStatus.PASS

    # 2. 缺少 rationale -> WARN
    details_poor = {"rationale": ""}
    res_poor = evaluate_economic_foundation(details_poor)
    assert res_poor.status == RubricStatus.WARN
    assert "缺少清晰的金融经济学因果逻辑说明" in res_poor.reason


def test_value_factor_diversity_computation_and_projection():
    submitted_alphas = [
        {"id": "a1", "classifications": [{"id": "SINGLE_DATA_SET"}], "pyramids": [{"name": "PriceVolume"}]},
        {"id": "a2", "classifications": [{"id": "SINGLE_DATA_SET"}], "pyramids": [{"name": "Analyst"}]},
        {"id": "a3", "classifications": [{"id": "MULTI_DATA_SET"}], "pyramids": [{"name": "Fundamental"}]},
    ]

    diversity = compute_value_factor_diversity(submitted_alphas, max_pyramids=10)

    assert diversity.N == 3
    assert diversity.A == 2
    assert diversity.P == 3
    assert abs(diversity.S_A - 2 / 3) < 0.01
    assert abs(diversity.S_P - 3 / 10) < 0.01
    assert diversity.S_H > 0.90  # 3 个不同类别分布非常均衡，熵接近 1.0
    assert diversity.diversity_score > 0.0

    # 增量推演: 提交一个覆盖全新类别 (Sentiment) 的 ATOM 因子
    candidate_atom_new_cat = {
        "classifications": [{"id": "SINGLE_DATA_SET"}],
        "pyramids": [{"name": "Sentiment"}],
    }
    projected, delta = project_diversity_after_submission(diversity, candidate_atom_new_cat)

    assert projected.N == 4
    assert projected.A == 3
    assert projected.P == 4
    assert delta > 0.0  # 多样性总分显著提升！


def test_alpha_judge_evaluator_verdicts_and_ranking():
    submitted = [
        {"id": "sub_1", "classifications": [{"id": "SINGLE_DATA_SET"}], "pyramids": [{"name": "PriceVolume"}]},
    ]
    judge = AlphaJudge(submitted_alphas=submitted)

    # 1. 优秀候选: 高夏普 + 纯信号 + 新金字塔类别 + 有逻辑 -> READY
    candidate_ready = {
        "alpha_id": "cand_01",
        "expression": "group_neutralize(ts_rank(est_eps_up, 22), subindustry)",
        "sharpe": 1.65,
        "fitness": 1.25,
        "turnover": 0.25,
        "pc_value": 0.20,
        "sc_value": 0.15,
        "rationale": "分析师一致预期上调加速动量超额收益",
        "classifications": [{"id": "SINGLE_DATA_SET"}],
        "pyramids": [{"name": "Analyst"}],
    }
    rep_ready = judge.judge_candidate(candidate_ready)
    assert rep_ready.verdict == JudgeVerdict.READY
    assert rep_ready.priority_score > 120.0
    assert rep_ready.projected_diversity_delta > 0.0

    # 2. 缺失逻辑说明候选 -> REVIEW
    candidate_review = {
        "alpha_id": "cand_02",
        "expression": "rank(close) / (rank(volume) + 0.01)",
        "sharpe": 1.45,
        "fitness": 1.10,
        "turnover": 0.30,
        "pc_value": 0.30,
        "sc_value": 0.20,
        "rationale": "",  # Missing!
        "classifications": [{"id": "SINGLE_DATA_SET"}],
        "pyramids": [{"name": "PriceVolume"}],
    }
    rep_review = judge.judge_candidate(candidate_review)
    assert rep_review.verdict == JudgeVerdict.REVIEW
    assert any("Economic foundation" in r.title for r in rep_review.rubric_results)

    # 3. 高相关性冲突候选 -> BLOCK
    candidate_block = {
        "alpha_id": "cand_03",
        "expression": "rank(close)",
        "sharpe": 1.50,
        "fitness": 1.10,
        "turnover": 0.20,
        "pc_value": 0.85,  # > 0.70 Violates prod correlation!
        "sc_value": 0.10,
        "rationale": "收盘价动量",
    }
    rep_block = judge.judge_candidate(candidate_block)
    assert rep_block.verdict == JudgeVerdict.BLOCK
    assert not rep_block.platform_checks_passed
    assert "HIGH_PROD_CORRELATION" in rep_block.failed_checks

    # 4. 候选列表排序: READY 应该排在第一位，其次 REVIEW，最后 BLOCK
    ranked = judge.rank_candidates([candidate_block, candidate_review, candidate_ready])
    assert [r.verdict for r in ranked] == [JudgeVerdict.READY, JudgeVerdict.REVIEW, JudgeVerdict.BLOCK]
    assert ranked[0].priority_score > ranked[1].priority_score > ranked[2].priority_score
