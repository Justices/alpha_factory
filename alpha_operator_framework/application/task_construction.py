"""Pure field-to-task construction used by simulation CLI adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


STANDARD_WINDOWS = (5, 22, 66, 120, 252, 504)
FIRST_ORDER_OPS = ("rank", "zscore", "quantile", "normalize", "ts_rank", "ts_zscore", "ts_delta", "ts_mean", "ts_std_dev", "ts_sum", "ts_delay")
VEC_OPS = ("vec_avg", "vec_sum", "vec_min", "vec_count", "vec_max", "vec_stddev", "vec_range")


@dataclass(frozen=True)
class FieldSpec:
    id: str
    dataset_id: str = ""
    type: str = "MATRIX"
    coverage: float = 0.0
    user_count: int = 0
    alpha_count: int = 0
    category: str = ""
    description: str = ""


def preprocess_field(field: FieldSpec, *, backfill: int = 120, winsorize_std: float = 4.0,
                     vector_ops: Sequence[str] = VEC_OPS) -> list[str]:
    if field.type == "MATRIX":
        bases = [field.id]
    elif field.type == "VECTOR":
        bases = [f"{operator}({field.id})" for operator in vector_ops]
    elif field.type == "EVENT":
        bases = [f"vec_avg({field.id})"]
    else:
        return []
    return [f"winsorize(ts_backfill({base}, {backfill}), std={winsorize_std:g})" for base in bases]


def preprocess_fields(fields: Iterable[FieldSpec], **kwargs: Any) -> list[str]:
    return [expression for field in fields for expression in preprocess_field(field, **kwargs)]


def first_order_factory(fields: Iterable[str], ops: Sequence[str] = FIRST_ORDER_OPS,
                        windows: Sequence[int] = STANDARD_WINDOWS) -> list[str]:
    expressions: list[str] = []
    for field in fields:
        expressions.append(field)
        for operator in ops:
            expressions.extend(
                f"{operator}({field}, {window})" for window in windows
            ) if operator.startswith("ts_") else expressions.append(f"{operator}({field})")
    return expressions


def load_task_pool(tasks: Sequence[dict[str, Any]], batch_size: int = 8, concurrency: int = 1) -> list[list[list[dict[str, Any]]]]:
    if not 2 <= batch_size <= 8:
        raise ValueError("batch_size must be in [2, 8] for create_multi_simulation")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    batches = [list(tasks[index:index + batch_size]) for index in range(0, len(tasks), batch_size)]
    return [batches[index:index + concurrency] for index in range(0, len(batches), concurrency)]
