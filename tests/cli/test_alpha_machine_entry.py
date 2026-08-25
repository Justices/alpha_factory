from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import alpha_machine
from alpha_operator_framework.cli import router


EXPECTED_DOMAINS = {
    "fields": {"discover", "prepare", "filter", "second-order"},
    "simulation": {"simulate", "poll-simulation"},
    "super_alpha": {"prepare-super", "simulate-super", "poll-super"},
    "research": {"research", "mine", "auto-pilot", "research-cycle", "research-worker", "research-rebuild"},
    "submission": {"submission-dispatch"},
    "operations": {"init-db", "clean-db", "storage-backup", "storage-restore", "drill-recovery", "status"},
}


def test_root_exposes_immutable_command_domains() -> None:
    domains = alpha_machine.command_domains()

    assert isinstance(domains, MappingProxyType)
    assert {name: set(commands) for name, commands in domains.items()} == EXPECTED_DOMAINS


def test_root_parser_registers_every_domain_command() -> None:
    parser = alpha_machine.build_parser()
    choices = next(action for action in parser._actions if action.dest == "command").choices

    assert set(choices) == set().union(*EXPECTED_DOMAINS.values())


def test_root_route_forwards_explicit_argv(monkeypatch) -> None:
    observed = []

    class Parser:
        def parse_args(self, argv):
            observed.append(argv)
            return SimpleNamespace(func=lambda args: ("routed", args.command), command="status")

    monkeypatch.setattr(router, "build_parser", lambda: Parser())

    assert alpha_machine.route(["status"]) == ("routed", "status")
    assert observed == [["status"]]


def test_root_main_delegates_to_route(monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(alpha_machine, "route", lambda argv=None: observed.append(argv))

    alpha_machine.main(["status"])

    assert observed == [["status"]]


def test_root_compatibility_facade_resolves_production_capabilities() -> None:
    expected = {
        "simulate", "command_simulate", "fetch_datafields", "field_from_dict", "select_fields", "write_json", "read_json",
        "QualityGate", "filter_alpha_results", "group_candidates",
        "FieldSpec", "preprocess_field", "fetch_user_alphas", "get_alpha_details",
    }

    assert expected <= set(dir(alpha_machine))
    assert all(callable(getattr(alpha_machine, name)) for name in expected)
