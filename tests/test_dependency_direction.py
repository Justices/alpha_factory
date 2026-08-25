"""Dependency boundaries for production modules."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "alpha_operator_framework"


def test_framework_modules_do_not_import_root_alpha_machine() -> None:
    """The root CLI facade must not be an internal production dependency."""
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "alpha_machine" for alias in node.names):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module == "alpha_machine":
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert not violations, "production imports of alpha_machine: " + ", ".join(violations)
