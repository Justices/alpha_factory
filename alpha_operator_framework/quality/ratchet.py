"""Deterministic quality-tool adapters and baseline comparison."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from numbers import Real
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import Any, Protocol

SCHEMA_VERSION = 1
_TOOLS = ("ruff", "mypy", "vulture")
_REQUIRED = (*_TOOLS, "coverage", "file_count")
_VERSIONED_TOOLS = (*_TOOLS, "coverage")


class BaselineError(ValueError):
    """Raised when a quality snapshot cannot be safely compared."""


class ToolFailure(RuntimeError):
    """Raised when a quality tool does not produce trustworthy output."""


@dataclass(frozen=True, slots=True)
class Issue:
    tool: str
    path: str
    code: str
    line: int | None
    message: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Small subprocess result contract used by injectable tool runners."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Execute one command and return captured text without raising on exit status."""

    def __call__(self, command: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    """Production runner with a fixed working directory and timeout."""

    def __init__(self, root: Path, timeout_seconds: float = 300.0) -> None:
        self._root = root
        self._timeout_seconds = timeout_seconds

    def __call__(self, command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            command,
            cwd=self._root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self._timeout_seconds,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def fingerprint(issue: Issue) -> str:
    """Return a stable issue identity, intentionally independent of line number."""
    path = Path(issue.path.replace("\\", "/")).as_posix()
    message = re.sub(r"\s+", " ", issue.message).strip()
    return f"{path}|{issue.code.strip()}|{message}"


def _normalize_path(value: str, root: Path) -> str:
    path = value.strip().replace("\\", "/")
    root_text = str(root.resolve()).replace("\\", "/").rstrip("/")
    if path.casefold() == root_text.casefold():
        return "."
    prefix = f"{root_text}/"
    if path.casefold().startswith(prefix.casefold()):
        path = path[len(prefix) :]
    while path.startswith("./"):
        path = path[2:]
    return Path(path).as_posix()


def _issue_key(issue: Issue) -> tuple[str, str, str, int, str]:
    return (issue.tool, issue.path, issue.code, issue.line or -1, issue.message)


def _deduplicate(issues: Sequence[Issue]) -> tuple[Issue, ...]:
    unique = {fingerprint(issue): issue for issue in issues}
    return tuple(sorted(unique.values(), key=_issue_key))


def _execute(runner: CommandRunner, command: Sequence[str], tool: str) -> CommandResult:
    try:
        result = runner(tuple(command))
    except (subprocess.TimeoutExpired, TimeoutError) as error:
        raise ToolFailure(f"{tool} timed out") from error
    except OSError as error:
        raise ToolFailure(f"{tool} could not start") from error
    except Exception as error:
        raise ToolFailure(f"{tool} runner crashed") from error
    combined = f"{result.stdout}\n{result.stderr}".casefold()
    if "traceback (most recent call last)" in combined:
        raise ToolFailure(f"{tool} produced a traceback")
    return result


def run_ruff(
    runner: CommandRunner,
    *,
    root: Path,
    python_executable: str = "python",
) -> tuple[Issue, ...]:
    """Run Ruff and normalize its JSON findings."""
    command = (
        python_executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--output-format",
        "json",
        "alpha_operator_framework",
        "tests",
        "tools",
    )
    result = _execute(runner, command, "ruff")
    if result.returncode not in (0, 1):
        raise ToolFailure(f"ruff failed with exit code {result.returncode}")
    try:
        rows = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise ToolFailure("ruff produced invalid JSON") from error
    if not isinstance(rows, list):
        raise ToolFailure("ruff JSON report must be a list")

    issues: list[Issue] = []
    try:
        for row in rows:
            location = row["location"]
            issues.append(
                Issue(
                    "ruff",
                    _normalize_path(str(row["filename"]), root),
                    str(row["code"]),
                    int(location["row"]),
                    str(row["message"]),
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        raise ToolFailure("ruff JSON report has an invalid finding") from error
    return _deduplicate(issues)


_MYPY_LINE = re.compile(
    r"^(?P<path>.+):(?P<line>\d+)(?::\d+)?: "
    r"(?P<severity>error|warning|note): (?P<message>.+)$"
)
_MYPY_CODE = re.compile(r" \[(?P<code>[^\]]+)\]$")


def _parse_mypy(output: str, root: Path) -> tuple[list[Issue], list[str]]:
    issues: list[Issue] = []
    invalid: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Found ", "Success: ")):
            continue
        match = _MYPY_LINE.match(stripped)
        if match is None:
            invalid.append(stripped)
            continue
        if match.group("severity") != "error":
            continue
        message = match.group("message")
        code_match = _MYPY_CODE.search(message)
        code = code_match.group("code") if code_match else "error"
        if code_match:
            message = message[: code_match.start()]
        issues.append(
            Issue(
                "mypy",
                _normalize_path(match.group("path"), root),
                code,
                int(match.group("line")),
                message,
            )
        )
    return issues, invalid


def run_mypy(
    runner: CommandRunner,
    *,
    files: Sequence[Path],
    root: Path,
    shard_size: int = 40,
    python_executable: str = "python",
) -> tuple[Issue, ...]:
    """Run Mypy over deterministic bounded shards of explicit Python files."""
    if shard_size < 1:
        raise ValueError("shard_size must be positive")
    relative_files = sorted(_normalize_path(str(path), root) for path in files)
    if not relative_files:
        raise ToolFailure("mypy scan found no Python files")

    issues: list[Issue] = []
    for start in range(0, len(relative_files), shard_size):
        shard = relative_files[start : start + shard_size]
        command = (
            python_executable,
            "-m",
            "mypy",
            *shard,
            "--follow-imports",
            "skip",
            "--ignore-missing-imports",
            "--no-incremental",
            "--cache-dir",
            os.devnull,
        )
        result = _execute(runner, command, "mypy")
        if result.returncode not in (0, 1):
            raise ToolFailure(f"mypy failed with exit code {result.returncode}")
        parsed, invalid = _parse_mypy(result.stdout, root)
        if invalid or (result.returncode == 1 and not parsed):
            raise ToolFailure("mypy produced unparseable output")
        issues.extend(parsed)
    return _deduplicate(issues)


def run_coverage(
    runner: CommandRunner,
    *,
    root: Path,
    python_executable: str = "python",
) -> float:
    """Read the total coverage percentage from a transient JSON report."""
    with tempfile.TemporaryDirectory(prefix="alpha-quality-") as directory:
        report = Path(directory) / "coverage.json"
        command = (python_executable, "-m", "coverage", "json", "-o", str(report))
        result = _execute(runner, command, "coverage")
        if result.returncode != 0:
            raise ToolFailure(f"coverage failed with exit code {result.returncode}")
        if not report.is_file():
            raise ToolFailure("coverage report is missing")
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            percent = payload["totals"]["percent_covered"]
            if isinstance(percent, bool) or not isinstance(percent, (int, float)):
                raise TypeError
            return float(percent)
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ToolFailure("coverage report is invalid") from error


_VULTURE_LINE = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): "
    r"(?P<message>(?P<description>.+) \((?P<confidence>\d+)% confidence\))$"
)


def run_vulture(
    runner: CommandRunner,
    *,
    root: Path,
    python_executable: str = "python",
) -> tuple[Issue, ...]:
    """Run Vulture and normalize its line-oriented findings."""
    command = (
        python_executable,
        "-m",
        "vulture",
        "alpha_operator_framework",
        "tools",
        "--min-confidence",
        "80",
    )
    result = _execute(runner, command, "vulture")
    if result.returncode not in (0, 3):
        raise ToolFailure(f"vulture failed with exit code {result.returncode}")
    issues: list[Issue] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        match = _VULTURE_LINE.match(line.strip())
        if match is None:
            raise ToolFailure("vulture produced unparseable output")
        confidence = int(match.group("confidence"))
        if confidence > 100:
            raise ToolFailure("vulture produced an invalid confidence")
        description = match.group("description").strip()
        if not description:
            raise ToolFailure("vulture produced unparseable output")
        issues.append(
            Issue(
                "vulture",
                _normalize_path(match.group("path"), root),
                description.split(maxsplit=1)[0].casefold(),
                int(match.group("line")),
                match.group("message"),
            )
        )
    if result.returncode == 3 and not issues:
        raise ToolFailure("vulture reported findings without parseable output")
    return _deduplicate(issues)


def collect_snapshot(
    runner: CommandRunner,
    *,
    root: Path,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    """Collect all quality signals without retaining raw tool output."""
    package = root / "alpha_operator_framework"
    files = tuple(sorted(package.rglob("*.py"))) if package.is_dir() else ()
    if not files:
        raise ToolFailure("quality scan found no Python files")
    return {
        "schema_version": SCHEMA_VERSION,
        "ruff": run_ruff(runner, root=root, python_executable=python_executable),
        "mypy": run_mypy(
            runner,
            files=files,
            root=root,
            python_executable=python_executable,
        ),
        "vulture": run_vulture(runner, root=root, python_executable=python_executable),
        "coverage": run_coverage(runner, root=root, python_executable=python_executable),
        "file_count": len(files),
    }


def baseline_payload(
    snapshot: Mapping[str, Any],
    *,
    versions: Mapping[str, str],
) -> dict[str, Any]:
    """Convert an in-memory snapshot into deterministic schema-v1 JSON data."""
    _validate(snapshot, "snapshot", allow_issues=True)
    _validate_versions(versions, "tool_versions")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_versions": dict(sorted(versions.items())),
        "ruff": sorted(_issues(snapshot, "ruff")),
        "mypy": sorted(_issues(snapshot, "mypy")),
        "vulture": sorted(_issues(snapshot, "vulture")),
        "coverage": math.floor(float(snapshot["coverage"])),
        "file_count": snapshot["file_count"],
    }


def write_baseline_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write baseline JSON through a same-directory temporary replacement."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="\n",
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


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


def _validate_versions(versions: object, label: str) -> None:
    if not isinstance(versions, Mapping):
        raise BaselineError(f"{label} must be a string map")
    if set(versions) != set(_VERSIONED_TOOLS):
        raise BaselineError(f"{label} must contain exactly: {', '.join(sorted(_VERSIONED_TOOLS))}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in versions.items()):
        raise BaselineError(f"{label} must be a string map")


def _validate(
    snapshot: Mapping[str, Any],
    label: str,
    *,
    allow_issues: bool,
    require_versions: bool = False,
) -> None:
    missing = [key for key in _REQUIRED if key not in snapshot]
    if missing:
        raise BaselineError(f"{label} missing required key(s): {', '.join(missing)}")
    schema_version = snapshot.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise BaselineError(f"{label} schema version must be {SCHEMA_VERSION}")
    coverage = snapshot["coverage"]
    if isinstance(coverage, bool) or not isinstance(coverage, Real) or not math.isfinite(float(coverage)):
        raise BaselineError(f"{label} coverage must be a finite real number")
    file_count = snapshot["file_count"]
    if type(file_count) is not int or file_count < 0:
        raise BaselineError(f"{label} file_count must be a non-negative integer")
    for tool in _TOOLS:
        values = snapshot[tool]
        if not isinstance(values, (list, tuple)):
            raise BaselineError(f"{tool} output must be a list or tuple")
        allowed = (str, Issue) if allow_issues else (str,)
        if not all(isinstance(value, allowed) for value in values):
            expected = "strings or Issue objects" if allow_issues else "strings"
            raise BaselineError(f"{tool} output must contain only {expected}")
    if require_versions:
        if "tool_versions" not in snapshot:
            raise BaselineError(f"{label} missing required key(s): tool_versions")
        _validate_versions(snapshot["tool_versions"], "tool_versions")


def validate_baseline(snapshot: Mapping[str, Any]) -> None:
    """Reject malformed persisted baseline data before running external tools."""
    _validate(snapshot, "baseline", allow_issues=False, require_versions=True)


def _issues(snapshot: Mapping[str, Any], tool: str) -> set[str]:
    values = snapshot[tool]
    result = set()
    for value in values:
        if isinstance(value, Issue):
            result.add(fingerprint(value))
        elif isinstance(value, str):
            result.add(value)
        else:
            raise BaselineError(f"{tool} output contains an invalid value")
    return result


def compare(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> ComparisonResult:
    """Compare two validated snapshots without mutating either input."""
    _validate(current, "current", allow_issues=True)
    validate_baseline(baseline)
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
