"""AST-equivalence pruning."""

from __future__ import annotations

from dataclasses import is_dataclass, replace
from typing import Any, Sequence


def ast_canonical_prune(tasks: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    """Canonicalize expressions and retain one task per equivalent expression."""
    from alpha_operator_framework.domain.ast import get_canonical_sha, to_canonical_string

    seen: set[str] = set()
    kept: list[Any] = []
    pruned: list[Any] = []
    for task in tasks:
        raw = task.expression if hasattr(task, "expression") else (task.get("expression") if isinstance(task, dict) else str(task))
        try:
            canonical = to_canonical_string(raw)
            digest = get_canonical_sha(canonical)
        except Exception:
            canonical, digest = raw, raw
        if digest in seen:
            pruned.append({**task, "prune_reason": "ast_duplicate", "canonical_expression": canonical} if isinstance(task, dict) else task)
            continue
        seen.add(digest)
        if canonical != raw and is_dataclass(task):
            kept.append(replace(task, expression=canonical))  # type: ignore[type-var]
        elif canonical != raw and isinstance(task, dict):
            kept.append({**task, "expression": canonical, "raw_expression": raw})
        else:
            kept.append(task)
    return kept, pruned
