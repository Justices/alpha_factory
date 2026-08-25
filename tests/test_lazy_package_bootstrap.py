"""Regression coverage for the package-root lazy bootstrap contract."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "package_root_exports.json"


def canonical_export(row: dict[str, str]) -> object:
    """Resolve one frozen export from its canonical module."""
    module = importlib.import_module(row["module"])
    if row["qualname"] == "<module>":
        return module
    return getattr(module, row["qualname"])


def cold_import_seconds(statement: str) -> float:
    """Measure an isolated import while blocking external side effects."""
    allowed_system_keys = ("COMSPEC", "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR")
    with tempfile.TemporaryDirectory() as isolated_root:
        isolated = Path(isolated_root)
        home = isolated / "home"
        config = isolated / "config"
        temp = isolated / "temp"
        for directory in (home, config, temp):
            directory.mkdir()
        env = {key: os.environ[key] for key in allowed_system_keys if key in os.environ}
        env.update(
            {
                "APPDATA": str(config),
                "HOME": str(home),
                "LOCALAPPDATA": str(config),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "TEMP": str(temp),
                "TMP": str(temp),
                "USERPROFILE": str(home),
                "XDG_CACHE_HOME": str(config / "cache"),
                "XDG_CONFIG_HOME": str(config),
                "XDG_DATA_HOME": str(config / "data"),
            }
        )
        program = textwrap.dedent(
            """
            import sqlite3
            import socket
            import time

            def prohibited(*args, **kwargs):
                raise RuntimeError("package import attempted prohibited external access")

            sqlite3.connect = prohibited
            socket.create_connection = prohibited
            socket.socket.connect = prohibited
            started = time.perf_counter()
            """
        )
        program += textwrap.dedent(statement)
        program += "\nprint(time.perf_counter() - started)\n"
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


def cold_cli_help_seconds() -> tuple[float, str]:
    """Measure one isolated CLI help process and return elapsed time and output."""
    allowed_system_keys = ("COMSPEC", "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR")
    with tempfile.TemporaryDirectory() as isolated_root:
        isolated = Path(isolated_root)
        home = isolated / "home"
        config = isolated / "config"
        temp = isolated / "temp"
        for directory in (home, config, temp):
            directory.mkdir()
        env = {key: os.environ[key] for key in allowed_system_keys if key in os.environ}
        env.update(
            {
                "APPDATA": str(config),
                "HOME": str(home),
                "LOCALAPPDATA": str(config),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "TEMP": str(temp),
                "TMP": str(temp),
                "USERPROFILE": str(home),
                "XDG_CACHE_HOME": str(config / "cache"),
                "XDG_CONFIG_HOME": str(config),
                "XDG_DATA_HOME": str(config / "data"),
            }
        )
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, str(ROOT / "alpha_machine.py"), "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        elapsed = time.perf_counter() - started
    assert completed.returncode == 0, completed.stderr
    return elapsed, completed.stdout


def test_package_root_matches_frozen_export_snapshot():
    package = importlib.import_module("alpha_operator_framework")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert sorted(package.__all__) == [row["name"] for row in expected]
    for row in expected:
        value = getattr(package, row["name"])
        assert value is canonical_export(row)
        assert package.__dict__[row["name"]] is value


def test_package_root_unknown_attribute_raises_and_resolved_export_is_cached():
    package = importlib.import_module("alpha_operator_framework")

    with pytest.raises(AttributeError):
        getattr(package, "__definitely_missing__")

    first = getattr(package, "Task")
    assert getattr(package, "Task") is first
    assert package.__dict__["Task"] is first


def test_canonical_export_resolves_container_constants_by_identity():
    package = importlib.import_module("alpha_operator_framework")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for name in ("BINARY_TEMPLATES", "PASS_STATES", "basic_ops"):
        row = next(item for item in expected if item["name"] == name)
        assert getattr(package, name) is canonical_export(row)


def test_cold_import_subprocess_uses_isolated_environment():
    credential_prefixes = (
        "ALPHA_",
        "ANTHROPIC_",
        "BRAIN_",
        "DASHSCOPE_",
        "DATABASE_",
        "DEEPSEEK_",
        "OPENAI_",
        "QWEN_",
    )
    cold_import_seconds(
        f"""
        import os
        assert not {{key for key in os.environ if key.startswith({credential_prefixes!r})}}
        assert os.environ['HOME'] != {str(Path.home())!r}
        assert os.environ['USERPROFILE'] != {os.environ.get('USERPROFILE', '')!r}
        """
    )


def test_package_root_cold_import_stays_under_ci_budget():
    samples = [cold_import_seconds("import alpha_operator_framework") for _ in range(3)]

    assert statistics.median(samples) < 2.5


def test_cli_help_cold_start_stays_under_ci_budget_and_lists_all_commands():
    import alpha_machine

    expected_commands = sorted(
        command for commands in alpha_machine.command_domains().values() for command in commands
    )
    samples_and_output = [cold_cli_help_seconds() for _ in range(3)]
    samples = [elapsed for elapsed, _ in samples_and_output]
    output = samples_and_output[0][1]

    assert statistics.median(samples) < 2.5
    assert len(expected_commands) == 22
    assert all(command in output for command in expected_commands)
