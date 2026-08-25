"""Repository contracts for the progressive quality baseline."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import alpha_operator_framework.quality as quality_api
from alpha_operator_framework.quality import ratchet
from alpha_operator_framework.quality.ratchet import SCHEMA_VERSION, baseline_payload


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_KEYS = {
    "schema_version",
    "tool_versions",
    "ruff",
    "mypy",
    "vulture",
    "file_count",
}
EXPECTED_VERSIONS = {
    "mypy": "1.17.1",
    "ruff": "0.12.11",
    "vulture": "2.16",
}


def test_quality_dependencies_exclude_coverage_and_pin_dead_code_once() -> None:
    lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()

    assert not any("coverage" in line.casefold() for line in lines)
    assert lines.count("vulture==2.16") == 1


def test_quality_configuration_excludes_coverage() -> None:
    with (ROOT / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    assert "coverage" not in config["tool"]


def test_baseline_payload_contains_only_schema_v2_quality_fields() -> None:
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "ruff": (),
        "mypy": (),
        "vulture": (),
        "file_count": 1,
    }

    payload = baseline_payload(snapshot, versions=EXPECTED_VERSIONS)

    assert set(payload) == EXPECTED_KEYS
    assert payload["schema_version"] == 2


def test_repository_baseline_has_normalized_schema_v2() -> None:
    baseline = json.loads((ROOT / "quality-baseline.json").read_text(encoding="utf-8"))

    assert set(baseline) == EXPECTED_KEYS
    assert baseline["schema_version"] == 2
    assert baseline["tool_versions"] == EXPECTED_VERSIONS
    for tool in ("ruff", "mypy", "vulture"):
        fingerprints = baseline[tool]
        assert fingerprints == sorted(set(fingerprints))
        assert all(isinstance(value, str) and value.count("|") >= 2 for value in fingerprints)
    completed = subprocess.run(
        ["rg", "--files", "alpha_operator_framework", "-g", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    package_files = [line for line in completed.stdout.splitlines() if line]
    assert baseline["file_count"] == len(package_files)


def test_quality_public_api_excludes_coverage_adapter() -> None:
    assert not hasattr(ratchet, "run_coverage")
    assert not hasattr(quality_api, "run_coverage")
