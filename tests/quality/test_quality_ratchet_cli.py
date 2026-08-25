import json
import subprocess
from pathlib import Path
import sys

import pytest

from alpha_operator_framework.quality.ratchet import (
    SCHEMA_VERSION,
    CommandResult,
    Issue,
    ToolFailure,
    collect_snapshot,
    run_coverage,
    run_mypy,
    run_ruff,
    run_vulture,
    write_baseline_atomic,
)
from tools.quality_ratchet import main


class _Runner:
    def __init__(self, responses=None, *, coverage=72.5):
        self.responses = responses or {}
        self.coverage = coverage
        self.commands = []

    def __call__(self, command):
        command = tuple(command)
        self.commands.append(command)
        module = command[2]
        if module == "coverage":
            report = Path(command[command.index("-o") + 1])
            report.write_text(
                json.dumps({"totals": {"percent_covered": self.coverage}}),
                encoding="utf-8",
            )
        default_stdout = "[]" if module == "ruff" else ""
        return self.responses.get(module, CommandResult(0, default_stdout, ""))


def _root_with_python_files(tmp_path: Path, count: int = 2) -> Path:
    root = tmp_path / "repo"
    package = root / "alpha_operator_framework"
    package.mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "tools").mkdir()
    for index in range(count):
        (package / f"module_{index}.py").write_text("value = 1\n", encoding="utf-8")
    return root


def _baseline(**overrides):
    value = {
        "schema_version": SCHEMA_VERSION,
        "tool_versions": {"coverage": "test", "mypy": "test", "ruff": "test", "vulture": "test"},
        "ruff": [],
        "mypy": [],
        "vulture": [],
        "coverage": 72.5,
        "file_count": 2,
    }
    value.update(overrides)
    return value


def test_ruff_json_finding_becomes_issue(tmp_path: Path):
    root = _root_with_python_files(tmp_path)
    output = json.dumps(
        [
            {
                "filename": str(root / "alpha_operator_framework" / "module_0.py"),
                "location": {"row": 7, "column": 1},
                "code": "F401",
                "message": "unused import os",
            }
        ]
    )
    runner = _Runner({"ruff": CommandResult(1, output, "")})

    assert run_ruff(runner, root=root) == (
        Issue("ruff", "alpha_operator_framework/module_0.py", "F401", 7, "unused import os"),
    )
    assert runner.commands == [
        (
            "python",
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
    ]


def test_mypy_parses_windows_drive_paths_and_shards_each_file_once(tmp_path: Path):
    root = _root_with_python_files(tmp_path, count=3)
    output = (
        rf"{root}\alpha_operator_framework\module_0.py:12: error: Incompatible types [assignment]"
    )
    runner = _Runner({"mypy": CommandResult(1, output, "")})
    files = tuple(sorted((root / "alpha_operator_framework").glob("*.py")))

    issues = run_mypy(runner, files=files, root=root, shard_size=2)

    assert issues == (
        Issue(
            "mypy",
            "alpha_operator_framework/module_0.py",
            "assignment",
            12,
            "Incompatible types",
        ),
    )
    mypy_commands = [command for command in runner.commands if command[2] == "mypy"]
    explicit_files = [part for command in mypy_commands for part in command[3:] if part.endswith(".py")]
    assert explicit_files == [
        "alpha_operator_framework/module_0.py",
        "alpha_operator_framework/module_1.py",
        "alpha_operator_framework/module_2.py",
    ]
    assert all("--no-incremental" in command for command in mypy_commands)


def test_coverage_reads_total_percent_from_json_report(tmp_path: Path):
    root = _root_with_python_files(tmp_path)

    assert run_coverage(_Runner(coverage=83.125), root=root) == pytest.approx(83.125)


def test_vulture_output_becomes_issue(tmp_path: Path):
    root = _root_with_python_files(tmp_path)
    runner = _Runner(
        {
            "vulture": CommandResult(
                3,
                "alpha_operator_framework/module_0.py:9: unused variable 'answer' (80% confidence)\n",
                "",
            )
        }
    )

    assert run_vulture(runner, root=root) == (
        Issue(
            "vulture",
            "alpha_operator_framework/module_0.py",
            "unused",
            9,
            "unused variable 'answer' (80% confidence)",
        ),
    )


@pytest.mark.parametrize(
    ("adapter", "module", "finding_exit_code"),
    [(run_ruff, "ruff", 1), (run_vulture, "vulture", 3)],
)
def test_parseable_finding_exit_code_is_accepted(
    adapter,
    module,
    finding_exit_code,
    tmp_path: Path,
):
    root = _root_with_python_files(tmp_path)
    outputs = {
        "ruff": '[{"filename":"x.py","location":{"row":1},"code":"F1","message":"bad"}]',
        "vulture": "x.py:1: unused variable 'x' (80% confidence)",
    }
    assert adapter(
        _Runner({module: CommandResult(finding_exit_code, outputs[module], "")}),
        root=root,
    )


@pytest.mark.parametrize("exit_code", [1, 2])
def test_vulture_rejects_nonstandard_exit_codes(exit_code: int, tmp_path: Path):
    root = _root_with_python_files(tmp_path)
    output = "x.py:1: unused variable 'x' (80% confidence)"

    with pytest.raises(ToolFailure, match="exit code"):
        run_vulture(
            _Runner({"vulture": CommandResult(exit_code, output, "")}),
            root=root,
        )


def test_vulture_accepts_unreachable_and_unsatisfiable_findings(tmp_path: Path):
    root = _root_with_python_files(tmp_path)
    output = "\n".join(
        [
            "alpha_operator_framework/module_0.py:7: unreachable code after 'return' (100% confidence)",
            "alpha_operator_framework/module_1.py:8: unsatisfiable 'if' condition (100% confidence)",
        ]
    )
    assert run_vulture(
        _Runner({"vulture": CommandResult(3, output, "")}),
        root=root,
    ) == (
        Issue(
            "vulture",
            "alpha_operator_framework/module_0.py",
            "unreachable",
            7,
            "unreachable code after 'return' (100% confidence)",
        ),
        Issue(
            "vulture",
            "alpha_operator_framework/module_1.py",
            "unsatisfiable",
            8,
            "unsatisfiable 'if' condition (100% confidence)",
        ),
    )


def test_vulture_rejects_blank_finding_description_as_tool_failure(tmp_path: Path):
    root = _root_with_python_files(tmp_path)

    with pytest.raises(ToolFailure, match="unparseable"):
        run_vulture(
            _Runner({"vulture": CommandResult(3, "x.py:1:   (80% confidence)", "")}),
            root=root,
        )


def test_timeout_and_traceback_raise_tool_failure(tmp_path: Path):
    root = _root_with_python_files(tmp_path)

    def timeout_runner(command):
        raise subprocess.TimeoutExpired(command, timeout=30)

    with pytest.raises(ToolFailure, match="timed out"):
        run_ruff(timeout_runner, root=root)
    with pytest.raises(ToolFailure, match="traceback"):
        run_vulture(
            _Runner({"vulture": CommandResult(1, "", "Traceback (most recent call last):\nboom")}),
            root=root,
        )


def test_unexpected_runner_crash_raises_tool_failure(tmp_path: Path):
    root = _root_with_python_files(tmp_path)

    def crashing_runner(command):
        raise RuntimeError("runner transport failed")

    with pytest.raises(ToolFailure, match="crashed"):
        run_ruff(crashing_runner, root=root)


def test_invalid_ruff_json_and_missing_coverage_report_raise_tool_failure(tmp_path: Path):
    root = _root_with_python_files(tmp_path)

    with pytest.raises(ToolFailure, match="JSON"):
        run_ruff(_Runner({"ruff": CommandResult(1, "not-json", "")}), root=root)

    class MissingReportRunner:
        def __call__(self, command):
            return CommandResult(0, "", "")

    with pytest.raises(ToolFailure, match="report"):
        run_coverage(MissingReportRunner(), root=root)


def test_collect_snapshot_rejects_missing_scan_target(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()

    with pytest.raises(ToolFailure, match="Python files"):
        collect_snapshot(_Runner(), root=root)


@pytest.mark.parametrize(
    ("baseline_overrides", "runner", "expected"),
    [
        ({}, _Runner(), 0),
        ({}, _Runner({"ruff": CommandResult(1, '[{"filename":"new.py","location":{"row":1},"code":"F1","message":"bad"}]', "")}), 1),
        ({}, _Runner(coverage=72.4), 1),
        ({"file_count": 3}, _Runner(), 1),
        ({}, _Runner({"ruff": CommandResult(2, "", "tool crashed")}), 1),
    ],
)
def test_check_exit_semantics(tmp_path: Path, capsys, baseline_overrides, runner, expected):
    root = _root_with_python_files(tmp_path)
    baseline = root / "quality-baseline.json"
    baseline.write_text(json.dumps(_baseline(**baseline_overrides)), encoding="utf-8")

    result = main(["check", "--baseline", str(baseline)], runner=runner, root=root)

    assert result == expected
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("[QUALITY]")
    assert len(lines) <= 11


def test_check_rejects_malformed_baseline_without_running_tools(tmp_path: Path, capsys):
    root = _root_with_python_files(tmp_path)
    baseline = root / "quality-baseline.json"
    baseline.write_text("{not-json", encoding="utf-8")
    runner = _Runner()

    assert main(["check", "--baseline", str(baseline)], runner=runner, root=root) == 1
    assert runner.commands == []
    assert capsys.readouterr().out.startswith("[QUALITY] FAIL")


def test_check_rejects_semantically_malformed_baseline_without_running_tools(
    tmp_path: Path,
    capsys,
):
    root = _root_with_python_files(tmp_path)
    baseline = root / "quality-baseline.json"
    baseline.write_text(json.dumps(_baseline(coverage=True)), encoding="utf-8")
    runner = _Runner()

    assert main(["check", "--baseline", str(baseline)], runner=runner, root=root) == 1
    assert runner.commands == []
    assert "coverage" in capsys.readouterr().out


def test_baseline_update_writes_deterministic_schema_v1_json_atomically(tmp_path: Path, capsys):
    root = _root_with_python_files(tmp_path)
    baseline = root / "nested" / "quality-baseline.json"
    baseline.parent.mkdir()
    baseline.write_text("old", encoding="utf-8")
    runner = _Runner(
        {
            "ruff": CommandResult(
                1,
                '[{"filename":"z.py","location":{"row":2},"code":"F2","message":"z"},'
                '{"filename":"a.py","location":{"row":1},"code":"F1","message":"a"}]',
                "",
            )
        }
    )

    assert main(
        ["baseline", "--update", "--baseline", str(baseline)],
        runner=runner,
        root=root,
        versions={"vulture": "2", "ruff": "1", "coverage": "3", "mypy": "4"},
    ) == 0
    first = baseline.read_text(encoding="utf-8")
    assert main(
        ["baseline", "--update", "--baseline", str(baseline)],
        runner=runner,
        root=root,
        versions={"vulture": "2", "ruff": "1", "coverage": "3", "mypy": "4"},
    ) == 0
    assert baseline.read_text(encoding="utf-8") == first
    assert json.loads(first) == {
        "coverage": 72.5,
        "file_count": 2,
        "mypy": [],
        "ruff": ["a.py|F1|a", "z.py|F2|z"],
        "schema_version": 1,
        "tool_versions": {"coverage": "3", "mypy": "4", "ruff": "1", "vulture": "2"},
        "vulture": [],
    }
    assert not list(baseline.parent.glob("*.tmp"))
    assert all(line.startswith("[QUALITY]") for line in capsys.readouterr().out.splitlines())


def test_atomic_writer_removes_temporary_file_when_serialization_fails(tmp_path: Path):
    baseline = tmp_path / "quality-baseline.json"
    baseline.write_text("original\n", encoding="utf-8")

    with pytest.raises(TypeError):
        write_baseline_atomic(baseline, {"not_json_serializable": object()})

    assert baseline.read_text(encoding="utf-8") == "original\n"
    assert not list(tmp_path.glob(".quality-baseline.json.*.tmp"))


def test_script_help_runs_from_the_repository_root():
    completed = subprocess.run(
        [sys.executable, "tools/quality_ratchet.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "check" in completed.stdout
    assert "baseline" in completed.stdout
