from __future__ import annotations

from alpha_operator_framework.application.task_construction import (
    FieldSpec,
    first_order_factory,
    load_task_pool,
    preprocess_fields,
)


def test_task_construction_builds_deterministic_pools() -> None:
    atomic = preprocess_fields([FieldSpec(id="returns")])
    expressions = first_order_factory(atomic, ops=("rank",), windows=(5,))
    pools = load_task_pool([{"expression": expression, "decay": 5} for expression in expressions], batch_size=2)

    assert atomic == ["winsorize(ts_backfill(returns, 120), std=4)"]
    assert expressions[-1] == "rank(winsorize(ts_backfill(returns, 120), std=4))"
    assert pools == [[[{"expression": expressions[0], "decay": 5}, {"expression": expressions[1], "decay": 5}]]]
