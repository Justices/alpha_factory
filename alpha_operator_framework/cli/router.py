"""CLI composition root: parser construction and command dispatch only."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from alpha_operator_framework.cli.command_registry import command_specs


def command_domains() -> Mapping[str, tuple[str, ...]]:
    """Return the stable command-domain catalog used by the system entry."""
    domains: dict[str, list[str]] = {}
    for spec in command_specs():
        domains.setdefault(spec.domain, []).append(spec.name)
    return MappingProxyType({domain: tuple(names) for domain, names in domains.items()})


def build_parser() -> argparse.ArgumentParser:
    """Build the root parser from the declarative command catalog."""
    parser = argparse.ArgumentParser(description="Alpha Factory command router")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for spec in command_specs():
        command = subparsers.add_parser(spec.name)
        spec.configure(command)
        command.set_defaults(**{spec.dispatch_attribute: spec.handler})
    return parser


def route(argv: Sequence[str] | None = None) -> Any:
    """Parse and dispatch one command, supporting embedded callers via ``argv``."""
    args = build_parser().parse_args(argv)
    handler = args.func if hasattr(args, "func") else args.handler
    return handler(args)


def main(argv: Sequence[str] | None = None) -> Any:
    return route(argv)
