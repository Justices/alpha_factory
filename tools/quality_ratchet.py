#!/usr/bin/env python3
"""Progressive full-tree quality ratchet with explicit baseline updates."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import importlib.metadata
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpha_operator_framework.quality.ratchet import (  # noqa: E402
    BaselineError,
    CommandRunner,
    SubprocessRunner,
    ToolFailure,
    baseline_payload,
    collect_snapshot,
    compare,
    validate_baseline,
    write_baseline_atomic,
)

_TOOL_DISTRIBUTIONS = {
    "coverage": "coverage",
    "mypy": "mypy",
    "ruff": "ruff",
    "vulture": "vulture",
}


def _versions() -> dict[str, str]:
    versions = {}
    for tool, distribution in _TOOL_DISTRIBUTIONS.items():
        try:
            versions[tool] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[tool] = "unavailable"
    return versions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare full-tree quality against a baseline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="fail on quality regressions")
    check.add_argument("--baseline", type=Path, default=Path("quality-baseline.json"))

    baseline = subparsers.add_parser("baseline", help="explicitly replace the quality baseline")
    baseline.add_argument("--update", action="store_true", required=True)
    baseline.add_argument("--baseline", type=Path, default=Path("quality-baseline.json"))
    return parser


def _load_baseline(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BaselineError("baseline file is missing") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BaselineError("baseline file is malformed") from error
    if not isinstance(payload, dict):
        raise BaselineError("baseline root must be an object")
    return payload


def _safe_reason(error: Exception) -> str:
    return " ".join(str(error).split())[:240] or error.__class__.__name__


def _run_check(path: Path, runner: CommandRunner, root: Path) -> int:
    try:
        baseline = _load_baseline(path)
        validate_baseline(baseline)
        snapshot = collect_snapshot(runner, root=root)
        result = compare(snapshot, baseline)
    except (BaselineError, ToolFailure) as error:
        print(f"[QUALITY] FAIL reason={_safe_reason(error)}")
        return 1

    new_fingerprints = [
        value
        for tool in sorted(result.new_issues)
        for value in result.new_issues[tool]
    ]
    status = "PASS" if result.passed else "FAIL"
    print(
        f"[QUALITY] {status} new={len(new_fingerprints)} "
        f"coverage={float(snapshot['coverage']):.3f} "
        f"baseline={float(baseline['coverage']):.3f} files={snapshot['file_count']}"
    )
    for value in new_fingerprints[:10]:
        print(f"[QUALITY] NEW {value}")
    return 0 if result.passed else 1


def _run_baseline(
    path: Path,
    runner: CommandRunner,
    root: Path,
    versions: Mapping[str, str],
) -> int:
    try:
        snapshot = collect_snapshot(runner, root=root)
        payload = baseline_payload(snapshot, versions=versions)
        write_baseline_atomic(path, payload)
    except (BaselineError, ToolFailure, OSError) as error:
        print(f"[QUALITY] FAIL reason={_safe_reason(error)}")
        return 1
    print(
        f"[QUALITY] BASELINE coverage={float(payload['coverage']):.3f} "
        f"files={payload['file_count']} ruff={len(payload['ruff'])} "
        f"mypy={len(payload['mypy'])} vulture={len(payload['vulture'])}"
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner | None = None,
    root: Path = ROOT,
    versions: Mapping[str, str] | None = None,
) -> int:
    """Run the requested quality command and return its stable exit code."""
    args = _parser().parse_args(argv)
    selected_runner = runner or SubprocessRunner(root)
    if args.command == "check":
        return _run_check(args.baseline, selected_runner, root)
    return _run_baseline(args.baseline, selected_runner, root, versions or _versions())


if __name__ == "__main__":
    raise SystemExit(main())
