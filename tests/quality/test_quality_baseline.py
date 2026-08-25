"""Repository contracts for the progressive quality baseline."""

from __future__ import annotations

import json
import math
import subprocess
import tomllib
from pathlib import Path

from alpha_operator_framework.quality.ratchet import baseline_payload


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_KEYS = {
    "schema_version",
    "tool_versions",
    "ruff",
    "mypy",
    "vulture",
    "coverage",
    "file_count",
}
EXPECTED_VERSIONS = {
    "coverage": "7.15.4",
    "mypy": "1.17.1",
    "ruff": "0.12.11",
    "vulture": "2.16",
}


def test_coverage_and_dead_code_dependencies_are_pinned_once() -> None:
    lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()

    assert lines.count("coverage==7.15.4") == 1
    assert lines.count("vulture==2.16") == 1


def test_branch_coverage_configuration_targets_the_package() -> None:
    with (ROOT / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    assert config["tool"]["coverage"]["run"] == {
        "branch": True,
        "source": ["alpha_operator_framework"],
    }
    assert config["tool"]["coverage"]["report"] == {
        "show_missing": True,
        "skip_covered": True,
    }


def test_baseline_payload_rounds_coverage_floor_down() -> None:
    snapshot = {
        "schema_version": 1,
        "tool_versions": EXPECTED_VERSIONS,
        "ruff": (),
        "mypy": (),
        "vulture": (),
        "coverage": 72.999,
        "file_count": 1,
    }

    payload = baseline_payload(snapshot, versions=EXPECTED_VERSIONS)

    assert payload["coverage"] == math.floor(snapshot["coverage"])


def test_repository_baseline_has_normalized_schema_v1() -> None:
    baseline = json.loads((ROOT / "quality-baseline.json").read_text(encoding="utf-8"))

    assert set(baseline) == EXPECTED_KEYS
    assert baseline["schema_version"] == 1
    assert baseline["tool_versions"] == EXPECTED_VERSIONS
    for tool in ("ruff", "mypy", "vulture"):
        fingerprints = baseline[tool]
        assert fingerprints == sorted(set(fingerprints))
        assert all(isinstance(value, str) and value.count("|") >= 2 for value in fingerprints)
    assert type(baseline["coverage"]) is int
    assert baseline["coverage"] >= 0

    completed = subprocess.run(
        ["rg", "--files", "alpha_operator_framework", "-g", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    package_files = [line for line in completed.stdout.splitlines() if line]
    assert baseline["file_count"] == len(package_files)
