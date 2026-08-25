"""Shared helpers for pruning components."""

from __future__ import annotations

from typing import Any


def metric(row: dict[str, Any], key: str) -> Any:
    """Read a simulation metric from the row or its ``is`` block."""
    if key in row:
        return row[key]
    return (row.get("is") or {}).get(key)


def number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
