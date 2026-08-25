"""Standalone CLI adapter for the event-led research lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence
from uuid import uuid4

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


def _config_path(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "config", DEFAULT_CONFIG_PATH))


def _round_id(args: argparse.Namespace, policy, options: dict[str, object]) -> str:
    explicit = getattr(args, "round_id", None)
    if explicit:
        return str(explicit)
    return f"research-{policy.region}-{policy.universe}-{options.get('seed', 42)}-{uuid4().hex[:8]}"


def _evidence(args: argparse.Namespace) -> dict[str, object] | None:
    authorized = bool(getattr(args, "authorize_submission", False))
    path = getattr(args, "submission_evidence_file", None)
    if authorized and not path:
        raise ValueError("--authorize-submission requires --submission-evidence-file")
    if path and not authorized:
        raise ValueError("--submission-evidence-file requires --authorize-submission")
    if not path:
        return None
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, dict):
        raise ValueError("submission evidence JSON must map platform alpha IDs to evidence records")
    return records


def command_research_cycle(args: argparse.Namespace) -> None:
    from alpha_operator_framework.application.research_cycle import ResearchCycleRequest
    from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime, resolve_research_options
    from alpha_operator_framework.infrastructure.telemetry import JsonLinesTelemetrySink
    from alpha_operator_framework.research.construction import AstCandidateBuilder, ConstructionTemplate
    from alpha_operator_framework.research.field_loader import load_real_market_fields
    from alpha_operator_framework.research.policy import load_policy, validate_cli_policy_overrides
    from alpha_operator_framework.research.round import ResearchPolicy

    config_path = _config_path(args)
    options = resolve_research_options(config_path, {
        name: getattr(args, name, None) for name in (
            "region", "universe", "delay", "decay", "neutralization", "truncation", "sample_per_family", "seed",
        )
    })
    policy_snapshot = load_policy(Path(args.policy_file)) if args.policy_file else None
    policy = policy_snapshot.to_research_policy() if policy_snapshot else None
    if getattr(args, "authorize_submission", False) and not args.execute:
        raise ValueError("--authorize-submission requires --execute")
    field_scope = {
        "region": policy.region if policy else options["region"],
        "universe": policy.universe if policy else options["universe"],
        "delay": policy.delay if policy else options.get("delay", 1),
    }
    fields = load_real_market_fields(
        **field_scope,
        datasets=args.datasets.split(",") if args.datasets else None,
        include_base_fields=False, allow_scope_fallback=False, category=getattr(args, "category", None),
    )
    if not fields:
        import asyncio
        from alpha_operator_framework.platform.datafields import fetch_datafields
        from alpha_operator_framework.research.field_loader import cache_platform_fields

        cache_platform_fields(asyncio.run(fetch_datafields(**field_scope)), **field_scope)
        fields = load_real_market_fields(
            **field_scope, datasets=args.datasets.split(",") if args.datasets else None,
            include_base_fields=False, allow_scope_fallback=False, category=getattr(args, "category", None),
        )
    if not fields:
        raise ValueError(f"no BRAIN data fields available for {field_scope['region']}/{field_scope['universe']}/delay={field_scope['delay']}")
    templates = policy_snapshot.construction_templates() if policy_snapshot and policy_snapshot.templates else (
        ConstructionTemplate("rank_field", "rank({field})", "cross_sectional", ("rank",)),
        ConstructionTemplate("ts_rank_22", "ts_rank({field}, 22)", "time_series", ("ts_rank",)),
    )
    candidates = AstCandidateBuilder().build(
        [field.id for field in fields if (field.type or "MATRIX").upper() == "MATRIX"], templates,
    )
    strategy = {"stratified": "weighted_stratified", "d_optimal": "diversity"}.get(
        args.algorithm or options.get("selection_strategy", "weighted_stratified"),
        args.algorithm or options.get("selection_strategy", "weighted_stratified"),
    )
    if policy is None:
        quota = options.get("sample_per_family", 4)
        policy = ResearchPolicy(
            options["region"], options["universe"], len(candidates) * quota,
            family_quotas={candidate.family: quota for candidate in candidates}, policy_version="cli-v1",
            selection_strategy=strategy, delay=options.get("delay", 1), decay=options.get("decay", 8),
            neutralization=options.get("neutralization", "SUBINDUSTRY"), truncation=options.get("truncation", 0.08),
        )
    else:
        validate_cli_policy_overrides(policy, {
            "region": getattr(args, "region", None), "universe": getattr(args, "universe", None), "delay": getattr(args, "delay", None),
            "algorithm": strategy if getattr(args, "algorithm", None) is not None else None, "decay": getattr(args, "decay", None),
            "neutralization": getattr(args, "neutralization", None), "truncation": getattr(args, "truncation", None),
        })
    runtime = build_research_runtime(
        config_path, execute_platform=args.execute, evidence_records=_evidence(args),
        submission_authorized=bool(getattr(args, "authorize_submission", False)),
    )
    try:
        round_id = _round_id(args, policy, options)
        summary = runtime.plan(ResearchCycleRequest(round_id, options.get("seed", 42), policy, runtime.knowledge_base.snapshot(), candidates, args.execute))
        if args.execute:
            summary = runtime.process_round(summary.round_id)
        if args.telemetry_file:
            JsonLinesTelemetrySink(Path(args.telemetry_file)).publish(runtime.telemetry)
        print(f"Research Cycle Summary\nresearch cycle: {summary.round_id} | {summary.status} | backtests={summary.completed_backtests}")
    finally:
        close = getattr(runtime, "close", None)
        if callable(close):
            close()


def command_research_worker(args: argparse.Namespace) -> None:
    from alpha_operator_framework.application.research_worker import ResearchWorkerScheduler
    from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime
    from alpha_operator_framework.infrastructure.telemetry import JsonLinesTelemetrySink

    runtime = build_research_runtime(
        _config_path(args), execute_platform=True, evidence_records=_evidence(args),
        submission_authorized=bool(args.authorize_submission),
    )
    try:
        if args.watch:
            summaries = ResearchWorkerScheduler(runtime.worker()).watch(poll_seconds=args.poll_seconds)
        else:
            if not args.round_id:
                raise ValueError("--round-id is required unless --watch is used")
            summaries = [runtime.process_round(args.round_id)]
        if args.telemetry_file:
            JsonLinesTelemetrySink(Path(args.telemetry_file)).publish(runtime.telemetry)
        for summary in summaries:
            print(f"research worker: {summary.round_id} | {summary.status} | backtests={summary.completed_backtests}")
    finally:
        close = getattr(runtime, "close", None)
        if callable(close):
            close()


def command_research_rebuild(args: argparse.Namespace) -> None:
    from alpha_operator_framework.application.research_rebuild import ResearchProjectionRebuilder
    from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime

    runtime = build_research_runtime(_config_path(args), execute_platform=False)
    try:
        ResearchProjectionRebuilder(runtime.event_store, runtime.research_repository, runtime.experiment_repository,
                                    runtime.knowledge_base, runtime.knowledge_repository).rebuild(args.round_id)
        print(f"research projections rebuilt: {args.round_id}")
    finally:
        close = getattr(runtime, "close", None)
        if callable(close):
            close()


def command_submission_dispatch(args: argparse.Namespace) -> None:
    from alpha_operator_framework.infrastructure.runtime_factory import build_submission_outbox
    from alpha_operator_framework.infrastructure.submission import CnhkMcpSubmissionGateway, SubmissionOutboxWorker

    outbox = build_submission_outbox(_config_path(args))
    dispatched = SubmissionOutboxWorker(outbox, CnhkMcpSubmissionGateway(), max_attempts=args.max_attempts).process_pending(args.limit)
    print(f"提交 outbox 已派发: {len(dispatched)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-cli", description="Event-led Alpha research lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)
    cycle = sub.add_parser("research-cycle")
    for name, kind in (("region", str), ("universe", str), ("delay", int), ("decay", int), ("neutralization", str), ("truncation", float)):
        cycle.add_argument(f"--{name}", type=kind)
    cycle.add_argument("--datasets")
    cycle.add_argument("--category")
    cycle.add_argument("--algorithm", choices=["stratified", "d_optimal", "thompson", "ucb", "diversity"])
    cycle.add_argument("--sample-per-family", type=int)
    cycle.add_argument("--seed", type=int, default=42)
    cycle.add_argument("--round-id")
    cycle.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    cycle.add_argument("--policy-file")
    cycle.add_argument("--telemetry-file")
    cycle.add_argument("--execute", action="store_true")
    cycle.add_argument("--authorize-submission", action="store_true")
    cycle.add_argument("--submission-evidence-file")
    cycle.set_defaults(handler=command_research_cycle)
    worker = sub.add_parser("research-worker")
    worker.add_argument("--round-id")
    worker.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    worker.add_argument("--telemetry-file")
    worker.add_argument("--authorize-submission", action="store_true")
    worker.add_argument("--submission-evidence-file")
    worker.add_argument("--watch", action="store_true")
    worker.add_argument("--poll-seconds", type=int, default=30)
    worker.set_defaults(handler=command_research_worker)
    rebuild = sub.add_parser("research-rebuild")
    rebuild.add_argument("--round-id", required=True)
    rebuild.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    rebuild.set_defaults(handler=command_research_rebuild)
    dispatch = sub.add_parser("submission-dispatch")
    dispatch.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    dispatch.add_argument("--limit", type=int, default=100)
    dispatch.add_argument("--max-attempts", type=int, default=3)
    dispatch.set_defaults(handler=command_submission_dispatch)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.handler(args)
