"""Deterministic, side-effect-free quality baseline comparison."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import re
from typing import Any

SCHEMA_VERSION = 1
_TOOLS = ("ruff", "mypy", "vulture")
_REQUIRED = (*_TOOLS, "coverage", "file_count")


class BaselineError(ValueError):
    """Raised when a quality snapshot cannot be safely compared."""


@dataclass(frozen=True, slots=True)
class Issue:
    tool: str
    path: str
    code: str
    line: int | None
    message: str


def fingerprint(issue: Issue) -> str:
    """Return a stable issue identity, intentionally independent of line number."""
    path = Path(issue.path.replace("\\", "/")).as_posix()
    message = re.sub(r"\s+", " ", issue.message).strip()
    return f"{path}|{issue.code.strip()}|{message}"


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    new_issues: Mapping[str, tuple[str, ...]]
    coverage_delta: float
    coverage_ok: bool
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "coverage_delta": self.coverage_delta,
            "coverage_ok": self.coverage_ok,
            "new_issues": {tool: list(values) for tool, values in self.new_issues.items()},
            "passed": self.passed,
        }


def _validate(snapshot: Mapping[str, Any], label: str) -> None:
    missing = [key for key in _REQUIRED if key not in snapshot]
    if missing:
        raise BaselineError(f"{label} missing required key(s): {', '.join(missing)}")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError(f"{label} schema version must be {SCHEMA_VERSION}")
    if not isinstance(snapshot["coverage"], (int, float)):
        raise BaselineError(f"{label} coverage must be numeric")
    if not isinstance(snapshot["file_count"], int) or snapshot["file_count"] < 0:
        raise BaselineError(f"{label} file_count must be a non-negative integer")


def _issues(snapshot: Mapping[str, Any], tool: str) -> set[str]:
    values = snapshot[tool]
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise BaselineError(f"{tool} output must be a collection")
    result = set()
    for value in values:
        result.add(fingerprint(value) if isinstance(value, Issue) else str(value))
    return result


def compare(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> ComparisonResult:
    """Compare two validated snapshots without mutating either input."""
    _validate(current, "current")
    _validate(baseline, "baseline")
    if current["file_count"] < baseline["file_count"]:
        raise BaselineError("current file_count is below baseline; scan target is missing")

    new = {
        tool: tuple(sorted(_issues(current, tool) - _issues(baseline, tool)))
        for tool in _TOOLS
    }
    new = {tool: values for tool, values in new.items() if values}
    delta = float(current["coverage"]) - float(baseline["coverage"])
    coverage_ok = delta >= 0
    return ComparisonResult(
        new_issues=MappingProxyType(new),
        coverage_delta=delta,
        coverage_ok=coverage_ok,
        passed=not new and coverage_ok,
    )
