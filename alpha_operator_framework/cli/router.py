"""CLI composition root: parser construction and command dispatch only."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from alpha_operator_framework.application.task_construction import STANDARD_WINDOWS
from alpha_operator_framework.cli import analysis, autopilot, field_pipeline, maintenance, recovery, research, simulation, status, super_alpha
from alpha_operator_framework.cli.research import DEFAULT_CONFIG_PATH


_COMMAND_DOMAINS: dict[str, tuple[str, ...]] = {
    "fields": ("discover", "prepare", "filter", "second-order"),
    "simulation": ("simulate", "poll-simulation"),
    "super_alpha": ("prepare-super", "simulate-super", "poll-super"),
    "research": ("research", "mine", "auto-pilot", "research-cycle", "research-worker", "research-rebuild"),
    "submission": ("submission-dispatch",),
    "operations": ("init-db", "clean-db", "storage-backup", "storage-restore", "drill-recovery", "status"),
}


def command_domains() -> Mapping[str, tuple[str, ...]]:
    """Return the stable command-domain catalog used by the system entry."""
    return MappingProxyType(_COMMAND_DOMAINS)


def _settings(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("--region", required=required)
    parser.add_argument("--universe", required=required)
    parser.add_argument("--delay", type=int, default=None if not required else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alpha Factory command router")
    sub = parser.add_subparsers(dest="command", required=True)
    discover = sub.add_parser("discover"); _settings(discover); discover.add_argument("--dataset", default=""); discover.add_argument("--search", default=""); discover.add_argument("--type", default=""); discover.add_argument("--min-coverage", type=float, default=0); discover.add_argument("--max-users", type=int); discover.add_argument("--require-used", action="store_true"); discover.add_argument("--limit", type=int, default=0); discover.add_argument("--output", required=True); discover.set_defaults(func=field_pipeline.command_discover)
    prepare = sub.add_parser("prepare"); prepare.add_argument("--fields", required=True); prepare.add_argument("--output", required=True); prepare.add_argument("--backfill", type=int, default=120); prepare.add_argument("--winsorize-std", type=float, default=4); prepare.add_argument("--windows", type=int, nargs="+", default=list(STANDARD_WINDOWS)); prepare.add_argument("--decays", default="6"); prepare.add_argument("--seed", type=int); prepare.add_argument("--batch-size", type=int, default=8); prepare.add_argument("--concurrency", type=int, default=1); prepare.set_defaults(func=field_pipeline.command_prepare)
    filtering = sub.add_parser("filter"); filtering.add_argument("--results", required=True); filtering.add_argument("--output", required=True); filtering.add_argument("--sharpe", type=float, default=1.2); filtering.add_argument("--fitness", type=float, default=.7); filtering.add_argument("--margin", type=float, default=5); filtering.add_argument("--min-turnover", type=float, default=.01); filtering.add_argument("--max-turnover", type=float, default=.7); filtering.add_argument("--require-sub-universe-pass", action="store_true"); filtering.add_argument("--require-2y-pass", action="store_true"); filtering.set_defaults(func=field_pipeline.command_filter)
    second = sub.add_parser("second-order"); _settings(second); second.add_argument("--winners", required=True); second.add_argument("--output", required=True); second.add_argument("--field-type", default="MATRIX"); second.add_argument("--category", default=""); second.add_argument("--groups-file", default=""); second.add_argument("--fetch-groups", action="store_true"); second.add_argument("--decays", default="6"); second.add_argument("--seed", type=int); second.add_argument("--batch-size", type=int, default=8); second.add_argument("--concurrency", type=int, default=1); second.set_defaults(func=field_pipeline.command_second_order)
    sim = sub.add_parser("simulate"); _settings(sim); sim.add_argument("--tasks", required=True); sim.add_argument("--output", required=True); sim.add_argument("--execute", action="store_true"); sim.add_argument("--batch-size", type=int, default=8); sim.add_argument("--neutralization", default="SUBINDUSTRY"); sim.add_argument("--truncation", type=float, default=.08); sim.add_argument("--nan-handling", default="OFF"); sim.add_argument("--test-period", default="P0Y0M"); sim.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); sim.set_defaults(func=simulation.command_simulate)
    poll = sub.add_parser("poll-simulation"); poll.add_argument("--batch-id", type=int, required=True); poll.add_argument("--output", required=True); poll.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); poll.set_defaults(func=simulation.command_poll_simulation)
    prepared = sub.add_parser("prepare-super"); _settings(prepared); prepared.add_argument("--output", required=True); prepared.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); prepared.add_argument("--max-candidates", type=int, default=6); prepared.add_argument("--decay", type=float, default=6); prepared.add_argument("--neutralization", default="SUBINDUSTRY"); prepared.add_argument("--truncation", type=float, default=.08); prepared.add_argument("--nan-handling", default="OFF"); prepared.set_defaults(func=super_alpha.command_prepare_super)
    super_sim = sub.add_parser("simulate-super"); _settings(super_sim); super_sim.add_argument("--candidates", required=True); super_sim.add_argument("--output", required=True); super_sim.add_argument("--execute", action="store_true"); super_sim.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); super_sim.add_argument("--decay", type=float, default=6); super_sim.add_argument("--neutralization", default="SUBINDUSTRY"); super_sim.add_argument("--truncation", type=float, default=.08); super_sim.add_argument("--nan-handling", default="OFF"); super_sim.set_defaults(func=super_alpha.command_simulate_super)
    super_poll = sub.add_parser("poll-super"); super_poll.add_argument("--batch-id", type=int, required=True); super_poll.add_argument("--output", required=True); super_poll.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); super_poll.set_defaults(func=simulation.command_poll_simulation)
    for name, handler in (("init-db", maintenance.command_init_db), ("storage-backup", maintenance.command_storage_backup), ("storage-restore", maintenance.command_storage_restore), ("clean-db", maintenance.command_clean_db)):
        command = sub.add_parser(name); command.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); command.set_defaults(func=handler)
        if name == "init-db": command.add_argument("--reset", action="store_true"); command.add_argument("--verify", action="store_true")
        elif name == "storage-backup": command.add_argument("--destination", required=True)
        elif name == "storage-restore": command.add_argument("--backup", required=True)
        elif name == "clean-db": command.add_argument("--mode", default="failed", choices=["failed", "pruned", "pending", "stale", "all_data"]); command.add_argument("--dry-run", action="store_true"); command.add_argument("--no-vacuum", action="store_true")
    drill = sub.add_parser("drill-recovery"); drill.add_argument("--temp", action="store_true", default=True); drill.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); drill.set_defaults(func=recovery.command_drill_recovery)
    dashboard = sub.add_parser("status"); dashboard.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); dashboard.set_defaults(func=status.command_status)
    research_parser = sub.add_parser("research"); research_parser.add_argument("--paper", required=True); _settings(research_parser, required=False); research_parser.add_argument("--neutralization", default="SUBINDUSTRY"); research_parser.add_argument("--decay", type=int, default=8); research_parser.add_argument("--datasets"); research_parser.add_argument("--use-llm", action="store_true"); research_parser.add_argument("--provider"); research_parser.add_argument("--model"); research_parser.add_argument("--execute", action="store_true"); research_parser.add_argument("--output"); research_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); research_parser.set_defaults(func=analysis.command_research)
    mine = sub.add_parser("mine"); _settings(mine); mine.add_argument("--datasets", required=True); mine.add_argument("--sample-per-family", type=int, default=4); mine.add_argument("--batch-size", type=int, default=5); mine.add_argument("--decay", type=int, default=12); mine.add_argument("--neutralization", default="SUBINDUSTRY"); mine.add_argument("--truncation", type=float, default=.08); mine.add_argument("--execute", action="store_true"); mine.add_argument("--seed", type=int); mine.add_argument("--output"); mine.set_defaults(func=analysis.command_mine)
    auto = sub.add_parser("auto-pilot"); _settings(auto); auto.add_argument("--config", default=str(DEFAULT_CONFIG_PATH)); auto.add_argument("--datasets", default="analyst7"); auto.add_argument("--paper"); auto.add_argument("--sample-per-family", type=int, default=4); auto.add_argument("--batch-size", type=int, default=5); auto.add_argument("--decay", type=int, default=12); auto.add_argument("--neutralization", default="SUBINDUSTRY"); auto.add_argument("--truncation", type=float, default=.08); auto.add_argument("--min-sharpe", type=float, default=1.25); auto.add_argument("--min-fitness", type=float, default=1.0); auto.add_argument("--execute", action="store_true"); auto.add_argument("--seed", type=int); auto.add_argument("--no-clean", action="store_true"); auto.add_argument("--output"); auto.set_defaults(func=autopilot.command_auto_pilot)
    cycle_parser = research.build_parser()
    for action in cycle_parser._subparsers._group_actions[0].choices.values():
        if action.prog.split()[-1] in {"research-cycle", "research-worker", "research-rebuild", "submission-dispatch"}:
            sub._name_parser_map[action.prog.split()[-1]] = action
    return parser


def route(argv: Sequence[str] | None = None) -> Any:
    """Parse and dispatch one command, supporting embedded callers via ``argv``."""
    args = build_parser().parse_args(argv)
    handler = args.func if hasattr(args, "func") else args.handler
    return handler(args)


def main(argv: Sequence[str] | None = None) -> Any:
    return route(argv)
