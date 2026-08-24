from __future__ import annotations

from alpha_operator_framework.cli.research import build_parser


def test_research_worker_watch_does_not_require_a_round_id() -> None:
    args = build_parser().parse_args(["research-worker", "--watch"])

    assert args.watch is True
    assert args.round_id is None


def test_research_parser_routes_rebuild_to_its_command() -> None:
    args = build_parser().parse_args(["research-rebuild", "--round-id", "round-1"])

    assert args.command == "research-rebuild"
    assert callable(args.handler)
