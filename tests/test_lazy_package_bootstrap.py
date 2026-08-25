"""Regression coverage for the package-root lazy bootstrap contract."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import textwrap
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "package_root_exports.json"


def export_location(value: object) -> tuple[str, str]:
    """Return the canonical module and qualified name for a package export."""
    if isinstance(value, types.ModuleType):
        return value.__name__, "<module>"
    return value.__module__, value.__qualname__  # type: ignore[attr-defined]


def cold_import_seconds(statement: str) -> float:
    """Measure an isolated import while blocking external side effects."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("BRAIN_", "OPENAI_", "ANTHROPIC_", "DATABASE_"))
    }
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
    program = textwrap.dedent(
        f"""
        import sqlite3
        import socket
        import time

        def prohibited(*args, **kwargs):
            raise RuntimeError("package import attempted prohibited external access")

        sqlite3.connect = prohibited
        socket.create_connection = prohibited
        socket.socket.connect = prohibited
        started = time.perf_counter()
        {statement}
        print(time.perf_counter() - started)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return float(completed.stdout.strip())


def test_package_root_matches_frozen_export_snapshot():
    package = importlib.import_module("alpha_operator_framework")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert sorted(package.__all__) == [row["name"] for row in expected]
    for row in expected:
        value = getattr(package, row["name"])
        assert export_location(value) == (row["module"], row["qualname"])


def test_package_root_unknown_attribute_raises_and_resolved_export_is_cached():
    package = importlib.import_module("alpha_operator_framework")

    with pytest.raises(AttributeError):
        getattr(package, "__definitely_missing__")

    first = getattr(package, "Task")
    assert getattr(package, "Task") is first


def test_package_root_cold_import_stays_under_ci_budget():
    samples = [cold_import_seconds("import alpha_operator_framework") for _ in range(3)]

    assert statistics.median(samples) < 2.5
