"""Contract tests for the repository's local and CI quality commands."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUALITY_MODULES = [
    "alpha_operator_framework/__init__.py",
    "alpha_operator_framework/cli/command_registry.py",
    "alpha_operator_framework/cli/router.py",
    "alpha_operator_framework/cache/datafields.py",
    "alpha_operator_framework/orchestration/**/*.py",
    "alpha_operator_framework/carpet/**/*.py",
    "alpha_operator_framework/workflow/**/*.py",
    "alpha_operator_framework/domain/pruning_components/**/*.py",
    "alpha_operator_framework/platform/alpha_source.py",
    "alpha_operator_framework/platform/datafield_ingest.py",
    "alpha_operator_framework/platform/simulation_gateway.py",
    "alpha_operator_framework/quality/**/*.py",
    "tools/quality_ratchet.py",
]


def test_quality_tool_configuration_targets_supported_python_and_module_scope() -> None:
    """Quality tools share explicit Python 3.12 and progressive module scope."""
    with (ROOT / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    pytest_options = config["tool"]["pytest"]["ini_options"]
    assert pytest_options["testpaths"] == ["tests"]
    markers = pytest_options["markers"]
    assert any(marker.startswith("unit:") for marker in markers)
    assert any(marker.startswith("integration:") for marker in markers)

    ruff_config = config["tool"]["ruff"]
    assert ruff_config["target-version"] == "py312"
    assert ruff_config["include"] == QUALITY_MODULES
    assert config["tool"]["ruff"]["lint"]["ignore"] == ["F401", "F541", "F841"]

    mypy_config = config["tool"]["mypy"]
    assert mypy_config["python_version"] == "3.12"
    assert mypy_config["files"] == QUALITY_MODULES
    assert "packages" not in mypy_config
    assert mypy_config["follow_imports"] == "skip"
    assert mypy_config["ignore_missing_imports"] is True


def test_development_dependencies_and_ci_use_the_quality_stack() -> None:
    """Pinned local tools and CI execute the same configured checks."""
    requirements = {
        line.split("==", maxsplit=1)[0]: line.split("==", maxsplit=1)[1]
        for line in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert all(requirements[tool] for tool in ("pytest", "ruff", "mypy"))

    workflow = (ROOT / ".github" / "workflows" / "recovery-drill.yml").read_text(
        encoding="utf-8"
    )
    assert "runs-on: windows-latest" in workflow
    assert "python-version: '3.12'" in workflow
    commands = re.findall(r"^\s*- run: (.+)$", workflow, flags=re.MULTILINE)
    assert "python -m pip install -r requirements-dev.txt" in commands
    assert "python -m compileall -q alpha_operator_framework alpha_machine.py" in commands
    assert "python -m ruff check ." in commands
    assert "python -m mypy" in commands
    assert "python tools/quality_ratchet.py check --baseline quality-baseline.json" in commands
    assert "python -m pytest -q" in commands
