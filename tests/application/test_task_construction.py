from __future__ import annotations

from alpha_operator_framework.application.task_construction import (
    FieldSpec,
    first_order_factory,
    load_task_pool,
    preprocess_fields,
)
from alpha_operator_framework.cli.field_pipeline import select_fields
from alpha_operator_framework.cli.simulation import normalize_platform_url
from alpha_operator_framework.cli.super_alpha import prepare_super_candidates


def test_task_construction_builds_deterministic_pools() -> None:
    atomic = preprocess_fields([FieldSpec(id="returns")])
    expressions = first_order_factory(atomic, ops=("rank",), windows=(5,))
    pools = load_task_pool([{"expression": expression, "decay": 5} for expression in expressions], batch_size=2)

    assert atomic == ["winsorize(ts_backfill(returns, 120), std=4)"]
    assert expressions[-1] == "rank(winsorize(ts_backfill(returns, 120), std=4))"
    assert pools == [[[{"expression": expressions[0], "decay": 5}, {"expression": expressions[1], "decay": 5}]]]


def test_field_pipeline_selects_platform_fields_without_legacy_module() -> None:
    fields = select_fields(
        [
            {"id": "slow", "dataset": {"id": "news"}, "type": "MATRIX", "coverage": 0.7},
            {"id": "best", "dataset": {"id": "news"}, "type": "MATRIX", "coverage": 0.9},
            {"id": "vector", "dataset": {"id": "news"}, "type": "VECTOR", "coverage": 0.99},
        ],
        dataset_id="news",
        data_type="MATRIX",
    )

    assert [field.id for field in fields] == ["best", "slow"]


def test_simulation_adapter_normalizes_platform_locations() -> None:
    assert normalize_platform_url("https://brain.example", "token") == "https://brain.example/simulations/token"
    assert normalize_platform_url("https://brain.example", "/simulations/token") == "https://brain.example/simulations/token"


def test_super_alpha_preparation_uses_the_supplied_repository() -> None:
    class Repository:
        def get_candidates_for_super_alpha(self): return []
        def save_super_candidates(self, candidates, settings): self.saved = candidates, settings

    repository = Repository()
    candidates = prepare_super_candidates(repository, {"region": "USA"})
    assert repository.saved == (candidates, {"region": "USA"})
