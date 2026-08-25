"""Dependency boundaries for production modules."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "alpha_operator_framework"
ALLOWED_PACKAGE_ROOT_IMPORT_FILES = {
    PACKAGE_ROOT / "__init__.py",
    PACKAGE_ROOT / "_lazy_exports.py",
}
FORBIDDEN_LAZY_EXPORT_TARGETS = {
    "alpha_operator_framework.ai_workflow",
    "alpha_operator_framework.carpet_mining",
    "alpha_operator_framework.orchestrator",
}


def package_root_import_violations(tree: ast.AST) -> list[int]:
    """Return lines importing the package root instead of a defining submodule."""
    violations: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "alpha_operator_framework":
            violations.append(node.lineno)
        elif isinstance(node, ast.Import) and any(
            alias.name == "alpha_operator_framework" for alias in node.names
        ):
            violations.append(node.lineno)
    return violations


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


def test_production_modules_do_not_import_package_root() -> None:
    """Internal modules must import defining modules, not root re-exports."""
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if path in ALLOWED_PACKAGE_ROOT_IMPORT_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{line}"
            for line in package_root_import_violations(tree)
        )

    assert not violations, "production imports of package root: " + ", ".join(violations)


def test_package_root_import_guard_rejects_aliased_root_import_fixture() -> None:
    """An aliased root import is forbidden, while actual submodule imports remain valid."""
    source = """
import alpha_operator_framework as af
import alpha_operator_framework.domain.fields
from alpha_operator_framework.domain import fields
"""

    assert package_root_import_violations(ast.parse(source)) == [2]


def test_lazy_exports_reject_legacy_monolith_targets() -> None:
    """Lazy exports must not resurrect the retired monolith modules."""
    from alpha_operator_framework._lazy_exports import EXPORTS

    targets = [module for module, _ in EXPORTS.values()]
    forbidden = sorted(FORBIDDEN_LAZY_EXPORT_TARGETS.intersection(targets))

    assert not forbidden, "forbidden lazy-export targets: " + ", ".join(forbidden)
