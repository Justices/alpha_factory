"""Two-stage template-correlation gates."""

from __future__ import annotations

import re


def structural_similarity(left: str, right: str) -> float:
    """Jaccard similarity over deterministic AST-like expression tokens."""
    left_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?", left))
    right_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?", right))
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def platform_correlation(self_correlation: float | None, production_correlation: float | None) -> float:
    return max(abs(float(self_correlation or 0.0)), abs(float(production_correlation or 0.0)))
