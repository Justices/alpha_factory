from __future__ import annotations

from alpha_operator_framework.cli.command_registry import command_specs
from alpha_operator_framework.cli import research, simulation, super_alpha
from alpha_operator_framework.cli.research import DEFAULT_CONFIG_PATH
from alpha_operator_framework.cli.router import build_parser, command_domains


EXPECTED_DOMAINS = {
    "fields",
    "simulation",
    "super_alpha",
    "research",
    "submission",
    "operations",
}

EXPECTED_COMMANDS = {
    "discover", "prepare", "filter", "second-order",
    "simulate", "poll-simulation",
    "prepare-super", "simulate-super", "poll-super",
    "init-db", "clean-db", "storage-backup", "storage-restore", "drill-recovery", "status",
    "research", "mine", "auto-pilot", "research-cycle", "research-worker", "research-rebuild",
    "submission-dispatch",
}

RESEARCH_LIFECYCLE_HANDLERS = {
    "research-cycle": research.command_research_cycle,
    "research-worker": research.command_research_worker,
    "research-rebuild": research.command_research_rebuild,
    "submission-dispatch": research.command_submission_dispatch,
}


def test_command_specs_are_routable_unique_and_well_formed() -> None:
    specs = command_specs()
    parser = build_parser()
    subcommands = next(action for action in parser._actions if action.dest == "command").choices

    assert len({spec.name for spec in specs}) == len(specs)
    assert {spec.domain for spec in specs} <= EXPECTED_DOMAINS
    assert all(callable(spec.handler) for spec in specs)
    assert {spec.name for spec in specs} == set(subcommands)
    assert {domain: set(commands) for domain, commands in command_domains().items()} == {
        domain: {spec.name for spec in specs if spec.domain == domain}
        for domain in EXPECTED_DOMAINS
    }


def test_root_parser_preserves_the_cli_contract() -> None:
    parser = build_parser()
    choices = next(action for action in parser._actions if action.dest == "command").choices

    assert set(choices) == EXPECTED_COMMANDS
    for command, handler in RESEARCH_LIFECYCLE_HANDLERS.items():
        args = parser.parse_args([command, "--round-id", "round-1"] if command == "research-rebuild" else [command])
        assert args.handler is handler
        assert not hasattr(args, "func")

    simulate = parser.parse_args([
        "simulate", "--region", "USA", "--universe", "TOP3000", "--tasks", "tasks.json", "--output", "results.json",
    ])
    assert simulate.func is simulation.command_simulate
    assert simulate.neutralization == "SUBINDUSTRY"
    assert simulate.config == str(DEFAULT_CONFIG_PATH)

    prepare_super = parser.parse_args([
        "prepare-super", "--region", "USA", "--universe", "TOP3000", "--output", "candidates.json",
    ])
    assert prepare_super.func is super_alpha.command_prepare_super
    assert prepare_super.decay == 6
