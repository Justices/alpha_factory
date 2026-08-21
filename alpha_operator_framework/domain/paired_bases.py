"""Explicit, economically meaningful binary base signals.

The CLI accepts pair specifications in the form
``kind:left:right[:denominator]``.  A pair is first made into a scalar base
signal and can then be expanded with the usual unary templates and first-order
operators.  Keeping this separate from automatic semantic pairing makes the
research hypothesis reproducible and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Iterable, Sequence

from alpha_operator_framework.domain.families import Task, first_order_task_factory, unary_factory
from alpha_operator_framework.domain.fields import DEFAULT_VEC_OPS, FieldSpec


_PAIR_KINDS = {"ratio", "difference", "spread", "net_revision"}
_EPSILON = "0.000001"


@dataclass(frozen=True)
class PairSpec:
    """One user-specified binary economic relationship."""

    kind: str
    left: str
    right: str
    denominator: str | None = None
    source: str = "explicit"


def parse_pair_spec(value: str) -> PairSpec:
    """Parse ``kind:left:right[:denominator]`` and validate its shape."""
    parts = [part.strip() for part in value.split(":")]
    if len(parts) not in (3, 4) or not all(parts):
        raise ValueError("--pair must be KIND:LEFT:RIGHT[:DENOMINATOR]")
    kind, left, right = parts[:3]
    kind = kind.lower()
    if kind not in _PAIR_KINDS:
        allowed = ", ".join(sorted(_PAIR_KINDS))
        raise ValueError(f"unsupported --pair kind {kind!r}; choose one of: {allowed}")
    if kind == "ratio" and len(parts) == 4:
        raise ValueError("ratio uses exactly two fields: ratio:NUMERATOR:DENOMINATOR")
    return PairSpec(kind=kind, left=left, right=right, denominator=parts[3] if len(parts) == 4 else None)


def parse_pair_specs(values: Iterable[str]) -> list[PairSpec]:
    return [parse_pair_spec(value) for value in values]


_REVISION_FIELD = re.compile(r"^(?P<key>.+)_(?P<direction>raisednum|lowerednum)_(?P<window>[^_]+)$", re.IGNORECASE)
_DISPERSION_FIELD = re.compile(r"^(?P<key>.+)_(?P<role>high|low|mean)$", re.IGNORECASE)


def discover_pair_specs(fields: Sequence[FieldSpec]) -> list[PairSpec]:
    """Discover strict same-dataset revision and dispersion field groups.

    Revision fields require matching ``<key>_raisednum_<window>`` and
    ``<key>_lowerednum_<window>`` plus the exact ``<key>_num`` denominator.
    Dispersion fields require exact ``<key>_high/_low/_mean`` trios.
    """
    eligible = [field for field in fields if field.type in ("MATRIX", "VECTOR")]
    by_dataset: dict[str, dict[str, FieldSpec]] = {}
    for field in eligible:
        by_dataset.setdefault(field.dataset_id, {})[field.id] = field

    discovered: list[PairSpec] = []
    for dataset_id in sorted(by_dataset):
        field_map = by_dataset[dataset_id]
        revisions: dict[tuple[str, str], dict[str, FieldSpec]] = {}
        dispersions: dict[str, dict[str, FieldSpec]] = {}
        for field in field_map.values():
            revision = _REVISION_FIELD.match(field.id)
            if revision:
                revisions.setdefault((revision.group("key"), revision.group("window")), {})[
                    revision.group("direction").lower()
                ] = field
            dispersion = _DISPERSION_FIELD.match(field.id)
            if dispersion:
                dispersions.setdefault(dispersion.group("key"), {})[dispersion.group("role").lower()] = field

        for (key, _window), members in sorted(revisions.items()):
            numerator = field_map.get(f"{key}_num")
            if numerator and "raisednum" in members and "lowerednum" in members:
                discovered.append(PairSpec(
                    "net_revision", members["raisednum"].id, members["lowerednum"].id,
                    numerator.id, "auto",
                ))
        for _key, members in sorted(dispersions.items()):
            if {"high", "low", "mean"} <= members.keys():
                discovered.append(PairSpec(
                    "spread", members["high"].id, members["low"].id,
                    members["mean"].id, "auto",
                ))
    return discovered


def paired_field_ids(pair_specs: Iterable[PairSpec]) -> set[str]:
    """Return every raw field consumed by an economic field group."""
    return {
        field_id
        for spec in pair_specs
        for field_id in (spec.left, spec.right, spec.denominator)
        if field_id
    }


def _field_map(fields: Sequence[FieldSpec]) -> dict[str, FieldSpec]:
    return {field.id: field for field in fields}


def _resolve(spec: PairSpec, fields: Sequence[FieldSpec]) -> tuple[FieldSpec, FieldSpec, FieldSpec | None]:
    available = _field_map(fields)
    missing = [field_id for field_id in (spec.left, spec.right, spec.denominator) if field_id and field_id not in available]
    if missing:
        raise ValueError(f"--pair references field(s) outside the selected pool: {', '.join(missing)}")
    left, right = available[spec.left], available[spec.right]
    denominator = available[spec.denominator] if spec.denominator else None
    involved = (left, right) + ((denominator,) if denominator else ())
    if any(field.type not in ("MATRIX", "VECTOR") for field in involved):
        raise ValueError("--pair fields must be MATRIX or VECTOR")
    datasets = {field.dataset_id for field in involved}
    if len(datasets) != 1:
        raise ValueError("--pair fields must belong to the same dataset")
    return left, right, denominator


def _raw_scalars(field: FieldSpec, vector_ops: Sequence[str]) -> list[str]:
    if field.type == "MATRIX":
        return [field.id]
    return [f"{operator}({field.id})" for operator in vector_ops]


def _pair_expression(spec: PairSpec, left: str, right: str, denominator: str | None) -> str:
    if spec.kind == "ratio":
        return f"({left} / ({right} + {_EPSILON}))"
    difference = f"({left} - {right})"
    if denominator:
        return f"({difference} / ({denominator} + {_EPSILON}))"
    return difference


def paired_base_task_factory(
    pair_specs: Sequence[PairSpec],
    fields: Sequence[FieldSpec],
    *,
    backfill: int = 120,
    winsorize_std: float = 4.0,
    vector_ops: Sequence[str] = DEFAULT_VEC_OPS,
    decay: float = 6.0,
) -> list[Task]:
    """Build preprocessed ratio/difference bases from explicit field pairs."""
    tasks: list[Task] = []
    seen: set[str] = set()
    for index, spec in enumerate(pair_specs):
        left, right, denominator = _resolve(spec, fields)
        left_scalars = _raw_scalars(left, vector_ops)
        right_scalars = _raw_scalars(right, vector_ops)
        denominator_scalars = _raw_scalars(denominator, vector_ops) if denominator else [None]
        for left_expr in left_scalars:
            for right_expr in right_scalars:
                for denominator_expr in denominator_scalars:
                    raw = _pair_expression(spec, left_expr, right_expr, denominator_expr)
                    expression = f"winsorize(ts_backfill({raw}, {backfill}), std={winsorize_std})"
                    if expression in seen:
                        continue
                    seen.add(expression)
                    source_fields = tuple(field.id for field in (left, right, denominator) if field is not None)
                    tasks.append(Task(
                        expression=expression,
                        template_index=-2000 - index,
                        family="paired_base",
                        fields_per_alpha=len(source_fields),
                        expression_origin="paired_base",
                        decay=decay,
                        base_fields=source_fields,
                        meta={
                            "label": f"paired_{spec.kind}",
                            "pair_kind": spec.kind,
                            "pair_source": spec.source,
                            "pair_stage": "base",
                            "pair_spec": ":".join((spec.kind, spec.left, spec.right) + ((spec.denominator,) if spec.denominator else ())),
                            "source_freq": "unknown",
                        },
                    ))
    return tasks


def _derived_pair_tasks(base_tasks: Sequence[Task], factory, origin: str, stage: str, ops_set=None) -> list[Task]:
    tasks: list[Task] = []
    for base in base_tasks:
        generated = factory([base.expression], ops_set) if ops_set is not None else factory([base.expression])
        for task in generated:
            meta = dict(base.meta)
            meta["pair_stage"] = stage
            meta["derived_template_index"] = task.template_index
            tasks.append(replace(
                task,
                fields_per_alpha=base.fields_per_alpha,
                expression_origin=origin,
                decay=base.decay,
                base_fields=base.base_fields,
                meta=meta,
            ))
    return tasks


def paired_unary_task_factory(base_tasks: Sequence[Task]) -> list[Task]:
    """Apply the fixed unary template family to each explicit pair base."""
    return _derived_pair_tasks(base_tasks, unary_factory, "paired_unary_template", "unary_template")


def paired_first_order_task_factory(base_tasks: Sequence[Task], ops_set=None) -> list[Task]:
    """Apply generic first-order operators to each explicit pair base."""
    return _derived_pair_tasks(base_tasks, first_order_task_factory, "paired_first_order", "first_order", ops_set)


def paired_group_first_order_task_factory(base_tasks: Sequence[Task], ops_set=None) -> list[Task]:
    """Apply first-order operators to the combined economic signal only."""
    return _derived_pair_tasks(
        base_tasks, first_order_task_factory, "paired_first_order", "combined_first_order", ops_set,
    )


__all__ = [
    "PairSpec",
    "parse_pair_spec",
    "parse_pair_specs",
    "discover_pair_specs",
    "paired_field_ids",
    "paired_base_task_factory",
    "paired_unary_task_factory",
    "paired_first_order_task_factory",
    "paired_group_first_order_task_factory",
]
