"""Declarative definitions for every command exposed by the system router."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

ParserConfigurer = Callable[[argparse.ArgumentParser], None]
CommandHandler = Callable[[argparse.Namespace], Any]
STANDARD_WINDOWS = (5, 22, 66, 120, 252, 504)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


@dataclass(frozen=True)
class LazyCommandHandler:
    """Resolve a command implementation only when the router dispatches it."""

    module_name: str
    attribute: str

    @property
    def __name__(self) -> str:
        """Preserve the function-name introspection used by CLI callers."""
        return self.attribute

    def __call__(self, args: argparse.Namespace) -> Any:
        handler = getattr(import_module(self.module_name), self.attribute)
        return handler(args)


@dataclass(frozen=True)
class CommandSpec:
    """One command's stable name, ownership domain, parser setup, and handler."""

    name: str
    domain: str
    configure: ParserConfigurer
    handler: CommandHandler
    dispatch_attribute: str = "func"


def _settings(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("--region", required=required)
    parser.add_argument("--universe", required=required)
    parser.add_argument("--delay", type=int, default=None if not required else 1)


def configure_discover(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--search", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--min-coverage", type=float, default=0)
    parser.add_argument("--max-users", type=int)
    parser.add_argument("--require-used", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", required=True)


def configure_prepare(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fields", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backfill", type=int, default=120)
    parser.add_argument("--winsorize-std", type=float, default=4)
    parser.add_argument("--windows", type=int, nargs="+", default=list(STANDARD_WINDOWS))
    parser.add_argument("--decays", default="6")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=1)


def configure_filter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sharpe", type=float, default=1.2)
    parser.add_argument("--fitness", type=float, default=.7)
    parser.add_argument("--margin", type=float, default=5)
    parser.add_argument("--min-turnover", type=float, default=.01)
    parser.add_argument("--max-turnover", type=float, default=.7)
    parser.add_argument("--require-sub-universe-pass", action="store_true")
    parser.add_argument("--require-2y-pass", action="store_true")


def configure_second_order(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    parser.add_argument("--winners", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--field-type", default="MATRIX")
    parser.add_argument("--category", default="")
    parser.add_argument("--groups-file", default="")
    parser.add_argument("--fetch-groups", action="store_true")
    parser.add_argument("--decays", default="6")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=1)


def configure_simulate(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--neutralization", default="SUBINDUSTRY")
    parser.add_argument("--truncation", type=float, default=.08)
    parser.add_argument("--nan-handling", default="OFF")
    parser.add_argument("--test-period", default="P0Y0M")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))


def configure_poll_simulation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--batch-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))


def configure_prepare_super(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--decay", type=float, default=6)
    parser.add_argument("--neutralization", default="SUBINDUSTRY")
    parser.add_argument("--truncation", type=float, default=.08)
    parser.add_argument("--nan-handling", default="OFF")


def configure_simulate_super(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--decay", type=float, default=6)
    parser.add_argument("--neutralization", default="SUBINDUSTRY")
    parser.add_argument("--truncation", type=float, default=.08)
    parser.add_argument("--nan-handling", default="OFF")


def configure_config_only(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))


def configure_init_db(parser: argparse.ArgumentParser) -> None:
    configure_config_only(parser)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--verify", action="store_true")


def configure_storage_backup(parser: argparse.ArgumentParser) -> None:
    configure_config_only(parser)
    parser.add_argument("--destination", required=True)


def configure_storage_restore(parser: argparse.ArgumentParser) -> None:
    configure_config_only(parser)
    parser.add_argument("--backup", required=True)


def configure_clean_db(parser: argparse.ArgumentParser) -> None:
    configure_config_only(parser)
    parser.add_argument("--mode", default="failed", choices=["failed", "pruned", "pending", "stale", "all_data"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-vacuum", action="store_true")


def configure_drill_recovery(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--temp", action="store_true", default=True)
    configure_config_only(parser)


def configure_research(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--paper", required=True)
    _settings(parser, required=False)
    parser.add_argument("--neutralization", default="SUBINDUSTRY")
    parser.add_argument("--decay", type=int, default=8)
    parser.add_argument("--datasets")
    parser.add_argument("--category")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output")
    configure_config_only(parser)


def configure_mine(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    parser.add_argument("--datasets", required=True)
    parser.add_argument("--sample-per-family", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--decay", type=int, default=12)
    parser.add_argument("--neutralization", default="SUBINDUSTRY")
    parser.add_argument("--truncation", type=float, default=.08)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output")


def configure_auto_pilot(parser: argparse.ArgumentParser) -> None:
    _settings(parser)
    configure_config_only(parser)
    parser.add_argument("--datasets", default="analyst7")
    parser.add_argument("--paper")
    parser.add_argument("--sample-per-family", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--decay", type=int, default=12)
    parser.add_argument("--neutralization", default="SUBINDUSTRY")
    parser.add_argument("--truncation", type=float, default=.08)
    parser.add_argument("--min-sharpe", type=float, default=1.25)
    parser.add_argument("--min-fitness", type=float, default=1.0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--output")


def configure_research_cycle(parser: argparse.ArgumentParser) -> None:
    for name, kind in (("region", str), ("universe", str), ("delay", int), ("decay", int), ("neutralization", str), ("truncation", float)):
        parser.add_argument(f"--{name}", type=kind)
    parser.add_argument("--datasets")
    parser.add_argument("--algorithm", choices=["stratified", "d_optimal", "thompson", "ucb", "diversity"])
    parser.add_argument("--sample-per-family", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--round-id")
    configure_config_only(parser)
    parser.add_argument("--policy-file")
    parser.add_argument("--telemetry-file")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize-submission", action="store_true")
    parser.add_argument("--submission-evidence-file")


def configure_research_worker(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--round-id")
    configure_config_only(parser)
    parser.add_argument("--telemetry-file")
    parser.add_argument("--authorize-submission", action="store_true")
    parser.add_argument("--submission-evidence-file")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)


def configure_research_rebuild(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--round-id", required=True)
    configure_config_only(parser)


def configure_submission_dispatch(parser: argparse.ArgumentParser) -> None:
    configure_config_only(parser)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=3)


def command_specs() -> tuple[CommandSpec, ...]:
    """Return the complete, immutable command catalog in help-display order."""
    return (
        CommandSpec("discover", "fields", configure_discover, LazyCommandHandler("alpha_operator_framework.cli.field_pipeline", "command_discover")),
        CommandSpec("prepare", "fields", configure_prepare, LazyCommandHandler("alpha_operator_framework.cli.field_pipeline", "command_prepare")),
        CommandSpec("filter", "fields", configure_filter, LazyCommandHandler("alpha_operator_framework.cli.field_pipeline", "command_filter")),
        CommandSpec("second-order", "fields", configure_second_order, LazyCommandHandler("alpha_operator_framework.cli.field_pipeline", "command_second_order")),
        CommandSpec("simulate", "simulation", configure_simulate, LazyCommandHandler("alpha_operator_framework.cli.simulation", "command_simulate")),
        CommandSpec("poll-simulation", "simulation", configure_poll_simulation, LazyCommandHandler("alpha_operator_framework.cli.simulation", "command_poll_simulation")),
        CommandSpec("prepare-super", "super_alpha", configure_prepare_super, LazyCommandHandler("alpha_operator_framework.cli.super_alpha", "command_prepare_super")),
        CommandSpec("simulate-super", "super_alpha", configure_simulate_super, LazyCommandHandler("alpha_operator_framework.cli.super_alpha", "command_simulate_super")),
        CommandSpec("poll-super", "super_alpha", configure_poll_simulation, LazyCommandHandler("alpha_operator_framework.cli.simulation", "command_poll_simulation")),
        CommandSpec("init-db", "operations", configure_init_db, LazyCommandHandler("alpha_operator_framework.cli.maintenance", "command_init_db")),
        CommandSpec("clean-db", "operations", configure_clean_db, LazyCommandHandler("alpha_operator_framework.cli.maintenance", "command_clean_db")),
        CommandSpec("storage-backup", "operations", configure_storage_backup, LazyCommandHandler("alpha_operator_framework.cli.maintenance", "command_storage_backup")),
        CommandSpec("storage-restore", "operations", configure_storage_restore, LazyCommandHandler("alpha_operator_framework.cli.maintenance", "command_storage_restore")),
        CommandSpec("drill-recovery", "operations", configure_drill_recovery, LazyCommandHandler("alpha_operator_framework.cli.recovery", "command_drill_recovery")),
        CommandSpec("status", "operations", configure_config_only, LazyCommandHandler("alpha_operator_framework.cli.status", "command_status")),
        CommandSpec("research", "research", configure_research, LazyCommandHandler("alpha_operator_framework.cli.analysis", "command_research")),
        CommandSpec("mine", "research", configure_mine, LazyCommandHandler("alpha_operator_framework.cli.analysis", "command_mine")),
        CommandSpec("auto-pilot", "research", configure_auto_pilot, LazyCommandHandler("alpha_operator_framework.cli.autopilot", "command_auto_pilot")),
        CommandSpec("research-cycle", "research", configure_research_cycle, LazyCommandHandler("alpha_operator_framework.cli.research", "command_research_cycle"), "handler"),
        CommandSpec("research-worker", "research", configure_research_worker, LazyCommandHandler("alpha_operator_framework.cli.research", "command_research_worker"), "handler"),
        CommandSpec("research-rebuild", "research", configure_research_rebuild, LazyCommandHandler("alpha_operator_framework.cli.research", "command_research_rebuild"), "handler"),
        CommandSpec("submission-dispatch", "submission", configure_submission_dispatch, LazyCommandHandler("alpha_operator_framework.cli.research", "command_submission_dispatch"), "handler"),
    )
