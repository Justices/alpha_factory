"""Unit tests for Phase 3 Symbolic Tree Breeder."""

from alpha_operator_framework.domain.ast.breeder import BreederConfig, SymbolicTreeBreeder
from alpha_operator_framework.domain.ast.validator import validate_expression


def test_symbolic_tree_breeder_unary():
    """验证单特征自由杂交生成的表达式 100% 语法合规."""
    breeder = SymbolicTreeBreeder(BreederConfig(seed=42))
    raw_exprs = breeder.breed_single_feature_expressions("est_fcf", "subindustry")

    assert len(raw_exprs) >= 15
    for expr in raw_exprs:
        v_res = validate_expression(expr)
        assert v_res.is_valid, f"Expression invalid: {expr}, err: {v_res.error_message}"


def test_symbolic_tree_breeder_pairwise():
    """验证双特征自由杂交生成的表达式 100% 语法合规."""
    breeder = SymbolicTreeBreeder(BreederConfig(seed=42))
    pair_exprs = breeder.breed_pairwise_expressions("est_fcf", "est_eps", "subindustry")

    assert len(pair_exprs) >= 4
    for expr in pair_exprs:
        v_res = validate_expression(expr)
        assert v_res.is_valid, f"Pairwise expression invalid: {expr}, err: {v_res.error_message}"


def test_symbolic_tree_breeder_task_cohort():
    """验证从字段清单全自动杂交产出 Task 列表."""
    fields = [
        {"id": "est_fcf", "type": "MATRIX", "dataset_id": "analyst7"},
        {"id": "est_eps", "type": "MATRIX", "dataset_id": "analyst7"},
        {"id": "rec_vec", "type": "VECTOR", "dataset_id": "analyst7"},
    ]
    breeder = SymbolicTreeBreeder(BreederConfig(seed=42))
    tasks = breeder.breed_task_cohort(fields)

    assert len(tasks) >= 30
    for t in tasks:
        assert t.family == "symbolic_evolution"
        assert t.expression
