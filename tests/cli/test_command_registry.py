from __future__ import annotations

from alpha_operator_framework.cli.command_registry import LazyCommandHandler, command_specs
from alpha_operator_framework.cli.research import DEFAULT_CONFIG_PATH
from alpha_operator_framework.cli.router import build_parser, command_domains
from alpha_operator_framework.infrastructure.runtime_factory import resolve_construction_plan


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

EXPECTED_HANDLER_REFS = {
    "research-cycle": ("alpha_operator_framework.cli.research", "command_research_cycle"),
    "research-worker": ("alpha_operator_framework.cli.research", "command_research_worker"),
    "research-rebuild": ("alpha_operator_framework.cli.research", "command_research_rebuild"),
    "submission-dispatch": ("alpha_operator_framework.cli.research", "command_submission_dispatch"),
    "simulate": ("alpha_operator_framework.cli.simulation", "command_simulate"),
    "prepare-super": ("alpha_operator_framework.cli.super_alpha", "command_prepare_super"),
}


def test_command_specs_are_routable_unique_and_well_formed() -> None:
    specs = command_specs()
    parser = build_parser()
    subcommands = next(action for action in parser._actions if action.dest == "command").choices

    assert len({spec.name for spec in specs}) == len(specs)
    assert {spec.domain for spec in specs} <= EXPECTED_DOMAINS
    assert all(isinstance(spec.handler, LazyCommandHandler) and callable(spec.handler) for spec in specs)
    assert {spec.name for spec in specs} == set(subcommands)
    assert {domain: set(commands) for domain, commands in command_domains().items()} == {
        domain: {spec.name for spec in specs if spec.domain == domain}
        for domain in EXPECTED_DOMAINS
    }


def test_root_parser_preserves_the_cli_contract() -> None:
    parser = build_parser()
    choices = next(action for action in parser._actions if action.dest == "command").choices

    assert set(choices) == EXPECTED_COMMANDS
    for command in ("research-cycle", "research-worker", "research-rebuild", "submission-dispatch"):
        args = parser.parse_args([command, "--round-id", "round-1"] if command == "research-rebuild" else [command])
        assert isinstance(args.handler, LazyCommandHandler)
        assert (args.handler.module_name, args.handler.attribute) == EXPECTED_HANDLER_REFS[command]
        assert not hasattr(args, "func")

    simulate = parser.parse_args([
        "simulate", "--region", "USA", "--universe", "TOP3000", "--tasks", "tasks.json", "--output", "results.json",
    ])
    assert isinstance(simulate.func, LazyCommandHandler)
    assert (simulate.func.module_name, simulate.func.attribute) == EXPECTED_HANDLER_REFS["simulate"]
    assert simulate.neutralization == "SUBINDUSTRY"
    assert simulate.config == str(DEFAULT_CONFIG_PATH)

    prepare_super = parser.parse_args([
        "prepare-super", "--region", "USA", "--universe", "TOP3000", "--output", "candidates.json",
    ])
    assert isinstance(prepare_super.func, LazyCommandHandler)
    assert (prepare_super.func.module_name, prepare_super.func.attribute) == EXPECTED_HANDLER_REFS["prepare-super"]
    assert prepare_super.decay == 6


def test_root_parser_accepts_continue_research_for_research_cycle() -> None:
    args = build_parser().parse_args([
        "research-cycle", "--region", "EUR", "--universe", "TOP2500",
        "--continue-research", "--execute",
    ])

    assert args.continue_research is True
    assert args.execute is True


def test_research_parser_accepts_tri_state_llm_overrides() -> None:
    parser = build_parser()

    default_args = parser.parse_args(["research", "--paper", "paper.md"])
    explicit_args = parser.parse_args([
        "research", "--paper", "paper.md", "--use-llm", "false",
        "--llm-config", "custom-llm.json", "--provider", "openai", "--model", "gpt-4o",
    ])

    assert default_args.use_llm is None
    assert default_args.llm_config is None
    assert explicit_args.use_llm is False
    assert explicit_args.llm_config == "custom-llm.json"
    assert explicit_args.provider == "openai"
    assert explicit_args.model == "gpt-4o"


def test_default_research_config_allocates_eight_backtests_per_leaf_family() -> None:
    plan = resolve_construction_plan(DEFAULT_CONFIG_PATH)

    assert {strategy.quota_per_leaf_family for strategy in plan.strategies} == {8}
    assert plan.platform_batch_size == 8
