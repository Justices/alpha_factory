from __future__ import annotations

import json


def test_legacy_command_exports_are_identical_to_new_package_exports() -> None:
    from alpha_operator_framework import orchestrator
    from alpha_operator_framework.orchestration import (
        cmd_deepen,
        cmd_run_all,
        cmd_submit,
        cmd_survey,
    )

    assert orchestrator.cmd_survey is cmd_survey
    assert orchestrator.cmd_deepen is cmd_deepen
    assert orchestrator.cmd_submit is cmd_submit
    assert orchestrator.cmd_run_all is cmd_run_all


def test_legacy_parser_routes_each_subcommand_to_new_handler() -> None:
    from alpha_operator_framework.orchestration import (
        cmd_deepen,
        cmd_run_all,
        cmd_submit,
        cmd_survey,
    )
    from alpha_operator_framework.orchestrator import build_parser

    parser = build_parser()
    routes = {
        "survey": ([], cmd_survey),
        "deepen": (["--density-out", "density.json"], cmd_deepen),
        "submit": (["--kept-out", "kept.json"], cmd_submit),
        "run-all": ([], cmd_run_all),
    }

    for command, (arguments, expected_handler) in routes.items():
        parsed = parser.parse_args([command, *arguments])
        assert parsed.command == command
        assert parsed.func is expected_handler


def test_deepen_dry_run_persists_tasks_without_simulation(
    monkeypatch, tmp_path
) -> None:
    from alpha_operator_framework.domain import density
    from alpha_operator_framework.orchestration import deepen
    from alpha_operator_framework.orchestrator import build_parser
    from alpha_operator_framework.platform import local_fields

    monkeypatch.setattr(density, "read_report", lambda _path: {"top_for_deepen": []})
    monkeypatch.setattr(local_fields, "load_local_field_specs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(deepen, "RUNS", tmp_path)

    async def reject_simulation(*_args, **_kwargs):
        raise AssertionError("dry-run must not call the simulation gateway")

    monkeypatch.setattr(deepen, "simulate", reject_simulation)
    args = build_parser().parse_args(
        [
            "deepen",
            "--density-out",
            "density.json",
            "--fields-file",
            "fields.json",
        ]
    )

    args.func(args)

    payload = json.loads((tmp_path / "deepen_tasks.json").read_text(encoding="utf-8"))
    assert payload == {
        "settings": {"stage": "deepen"},
        "tasks": [],
        "annotated": [],
    }
