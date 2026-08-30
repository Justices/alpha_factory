"""Field discovery and expression construction command adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from alpha_operator_framework.application.task_construction import (
    FieldSpec,
    first_order_factory,
    load_task_pool,
    preprocess_fields,
)
from alpha_operator_framework.platform.datafields import fetch_datafields

GROUP_OPS = ("group_neutralize", "group_rank", "group_zscore")


@dataclass(frozen=True)
class QualityGate:
    sharpe: float = 1.2
    fitness: float = 0.7
    margin: float = 5.0
    min_turnover: float = 0.01
    max_turnover: float = 0.70
    require_sub_universe_pass: bool = False
    require_2y_pass: bool = False


def field_from_dict(row: dict[str, Any]) -> FieldSpec:
    category = row.get("category") or row.get("category_name") or ""
    if isinstance(category, dict):
        category = str(category.get("id") or "")
    return FieldSpec(
        id=str(row["id"]),
        dataset_id=str(
            row.get("dataset_id") or (row.get("dataset") or {}).get("id") or ""
        ),
        type=str(row.get("type") or "MATRIX").upper(),
        coverage=float(row.get("coverage") or 0),
        user_count=int(row.get("userCount") or row.get("user_count") or 0),
        alpha_count=int(row.get("alphaCount") or row.get("alpha_count") or 0),
        category=str(category),
        description=str(row.get("description") or ""),
    )


def select_fields(
    rows: Iterable[dict[str, Any]],
    *,
    dataset_id: str = "",
    data_type: str = "",
    min_coverage: float = 0.0,
    max_users: int | None = None,
    require_used: bool = False,
    limit: int = 0,
) -> list[FieldSpec]:
    selected = [field_from_dict(row) for row in rows]
    selected = [
        field
        for field in selected
        if (not dataset_id or field.dataset_id == dataset_id)
        and (not data_type or field.type == data_type.upper())
        and field.coverage >= min_coverage
        and (max_users is None or field.user_count <= max_users)
        and (not require_used or field.user_count > 0)
    ]
    selected.sort(
        key=lambda field: (
            -field.coverage,
            field.user_count,
            -field.alpha_count,
            field.id,
        )
    )
    return selected[:limit] if limit else selected


def group_candidates(
    region: str,
    *,
    field_type: str = "MATRIX",
    category: str = "",
    available_groups: Sequence[FieldSpec] = (),
) -> list[str]:
    del region
    base = ["market", "sector", "industry", "subindustry"]
    structural = [
        "bucket(rank(cap), range='0.1, 1, 0.1')",
        "bucket(rank(vwap * volume), range='0.1, 1, 0.1')",
    ]
    category = category.lower()
    if any(
        key in category
        for key in ("fundamental", "analyst", "earnings", "value", "quality")
    ):
        structural.insert(1, "bucket(rank(assets), range='0.1, 1, 0.1')")
    if any(key in category for key in ("pv", "price", "volume", "risk", "sentiment")):
        structural.append("bucket(rank(ts_std_dev(returns, 20)), range='0.1, 1, 0.1')")
    dynamic = [
        field.id
        for field in sorted(
            available_groups,
            key=lambda field: (-field.coverage, field.user_count, field.id),
        )
        if field.type == "GROUP"
    ]
    return list(
        dict.fromkeys(
            (
                base[1:] + structural[-2:]
                if field_type.upper() == "VECTOR"
                else base + structural
            )
            + dynamic
        )
    )


def second_order_factory(
    expressions: Iterable[str],
    region: str,
    *,
    field_type: str = "MATRIX",
    category: str = "",
    ops: Sequence[str] = GROUP_OPS,
    available_groups: Sequence[FieldSpec] = (),
) -> list[str]:
    invalid = set(ops).difference(GROUP_OPS)
    if invalid:
        raise ValueError(f"unsupported group operators: {sorted(invalid)}")
    groups = group_candidates(
        region,
        field_type=field_type,
        category=category,
        available_groups=available_groups,
    )
    return [
        f"{op}({expression}, densify({group}))"
        for expression in expressions
        for op in ops
        for group in groups
    ]


def pair_and_shuffle(
    expressions: Iterable[str], decays: Sequence[float], seed: int | None
) -> list[dict[str, Any]]:
    tasks = [
        {"expression": expression, "decay": decay}
        for expression in expressions
        for decay in decays
    ]
    random.Random(seed).shuffle(tasks)
    return tasks


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _parse_decays(raw: str) -> tuple[float, ...]:
    values = tuple(float(value.strip()) for value in raw.split(",") if value.strip())
    if not values:
        raise ValueError("at least one decay is required")
    return values


def _metric(row: dict[str, Any], key: str) -> Any:
    return row.get(key, (row.get("is") or {}).get(key))


def filter_alpha_results(
    rows: Iterable[dict[str, Any]], gate: QualityGate
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept, rejected = [], []
    for row in rows:
        sharpe, fitness, margin, turnover = (
            _metric(row, key) for key in ("sharpe", "fitness", "margin", "turnover")
        )
        reasons = [
            key
            for key, value, threshold in (
                ("sharpe", sharpe, gate.sharpe),
                ("fitness", fitness, gate.fitness),
                ("margin", margin, gate.margin),
            )
            if not isinstance(value, (int, float)) or value <= threshold
        ]
        if (
            isinstance(turnover, (int, float))
            and not gate.min_turnover <= turnover <= gate.max_turnover
        ):
            reasons.append("turnover")
        checks = {
            check.get("name"): check.get("result")
            for check in ((row.get("is") or {}).get("checks") or [])
            if isinstance(check, dict)
        }
        if (
            gate.require_sub_universe_pass
            and checks.get("LOW_SUB_UNIVERSE_SHARPE") != "PASS"
        ):
            reasons.append("sub_universe")
        if gate.require_2y_pass and checks.get("LOW_2Y_SHARPE") != "PASS":
            reasons.append("low_2y")
        (kept if not reasons else rejected).append({**row, "filter_reasons": reasons})
    kept.sort(
        key=lambda row: (
            _metric(row, "sharpe") or -999,
            _metric(row, "fitness") or -999,
        ),
        reverse=True,
    )
    return kept, rejected


def command_discover(args: argparse.Namespace) -> None:
    rows = asyncio.run(
        fetch_datafields(
            args.region, args.universe, args.delay, args.dataset, args.search, args.type
        )
    )
    fields = select_fields(
        rows,
        dataset_id=args.dataset,
        data_type=args.type,
        min_coverage=args.min_coverage,
        max_users=args.max_users,
        require_used=args.require_used,
        limit=args.limit,
    )
    _write_json(
        Path(args.output),
        {"settings": vars(args), "fields": [asdict(field) for field in fields]},
    )
    print(f"fields={len(fields)} output={args.output}")


def command_prepare(args: argparse.Namespace) -> None:
    payload = _read_json(Path(args.fields))
    fields = [field_from_dict(row) for row in payload.get("fields", payload)]
    atomic = preprocess_fields(
        fields, backfill=args.backfill, winsorize_std=args.winsorize_std
    )
    expressions = first_order_factory(atomic, windows=tuple(args.windows))
    tasks = pair_and_shuffle(expressions, _parse_decays(args.decays), args.seed)
    _write_json(
        Path(args.output),
        {
            "fields": [asdict(field) for field in fields],
            "atomic_fields": atomic,
            "first_order_expressions": expressions,
            "tasks": tasks,
            "pools": load_task_pool(tasks, args.batch_size, args.concurrency),
        },
    )
    print(
        f"atomic={len(atomic)} first_order={len(expressions)} tasks={len(tasks)} output={args.output}"
    )


def command_filter(args: argparse.Namespace) -> None:
    payload = _read_json(Path(args.results))
    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    kept, rejected = filter_alpha_results(
        rows,
        QualityGate(
            args.sharpe,
            args.fitness,
            args.margin,
            args.min_turnover,
            args.max_turnover,
            args.require_sub_universe_pass,
            args.require_2y_pass,
        ),
    )
    _write_json(
        Path(args.output),
        {
            "gate": asdict(
                QualityGate(
                    args.sharpe,
                    args.fitness,
                    args.margin,
                    args.min_turnover,
                    args.max_turnover,
                    args.require_sub_universe_pass,
                    args.require_2y_pass,
                )
            ),
            "kept": kept,
            "rejected": rejected,
        },
    )
    print(f"kept={len(kept)} rejected={len(rejected)} output={args.output}")


def command_second_order(args: argparse.Namespace) -> None:
    payload = _read_json(Path(args.winners))
    winners = payload.get("kept", payload) if isinstance(payload, dict) else payload
    group_fields: list[FieldSpec] = []
    if args.groups_file:
        group_fields = [
            field_from_dict(row)
            for row in _read_json(Path(args.groups_file)).get(
                "fields", _read_json(Path(args.groups_file))
            )
        ]
    elif args.fetch_groups:
        group_fields = [
            field_from_dict(row)
            for row in asyncio.run(
                fetch_datafields(
                    args.region, args.universe, args.delay, data_type="GROUP"
                )
            )
        ]
    expressions = [
        row.get("expression") or row.get("regular", {}).get("code") for row in winners
    ]
    second = second_order_factory(
        [expression for expression in expressions if expression],
        args.region,
        field_type=args.field_type,
        category=args.category,
        available_groups=group_fields,
    )
    tasks = pair_and_shuffle(second, _parse_decays(args.decays), args.seed)
    _write_json(
        Path(args.output),
        {
            "source_count": len(expressions),
            "group_fields": [asdict(field) for field in group_fields],
            "expressions": second,
            "tasks": tasks,
            "pools": load_task_pool(tasks, args.batch_size, args.concurrency),
        },
    )
    print(f"second_order={len(second)} tasks={len(tasks)} output={args.output}")


__all__ = [
    "command_discover",
    "command_prepare",
    "command_filter",
    "command_second_order",
    "fetch_datafields",
    "select_fields",
    "second_order_factory",
]
