"""Super Alpha candidate and simulation command adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Sequence

from alpha_operator_framework.generation.super_alpha import SuperAlphaConfig, build_super_candidates, super_simulation_payload
from alpha_operator_framework.infrastructure.maintenance import open_alpha_database
from alpha_operator_framework.platform.simulation_tracker import SimulationTracker

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


def prepare_super_candidates(database: Any, settings: dict[str, Any], *, max_candidates: int = 6) -> list[dict[str, Any]]:
    candidates = build_super_candidates(database.get_candidates_for_super_alpha(), SuperAlphaConfig(max_candidates=max_candidates), settings)
    database.save_super_candidates(candidates, settings)
    return candidates


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


async def simulate_super(candidates: Sequence[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    from cnhkmcp.untracked.platform_functions import brain_client
    await brain_client.ensure_authenticated()
    settings = {"region": args.region, "universe": args.universe, "delay": args.delay, "decay": args.decay, "neutralization": args.neutralization, "truncation": args.truncation, "nan_handling": args.nan_handling, "simulation_type": "SUPER"}
    results = []
    for candidate in candidates:
        database = open_alpha_database(Path(getattr(args, "config", DEFAULT_CONFIG_PATH)))
        try:
            task = {**candidate, "expression": candidate["candidate_sha"], "decay": args.decay}
            def submit(tasks: list[dict[str, Any]]) -> str:
                payload = super_simulation_payload(tasks[0], {"instrumentType": "EQUITY", **settings, "pasteurization": "ON", "unitHandling": "VERIFY", "language": "FASTEXPR", "visualization": False})
                response = brain_client.session.post(f"{brain_client.base_url}/simulations", json=payload); response.raise_for_status()
                location = response.headers.get("Location")
                if not location: raise RuntimeError("platform did not return a simulation Location")
                return location
            batch_id = SimulationTracker(database, submit=submit, fetch=lambda _: ({}, 0), detail=lambda _: {}).submit([task], settings)
            results.append({"candidate_sha": candidate["candidate_sha"], "simulation_batch_id": batch_id, "status": "submitted"})
        finally:
            database.close()
    return results


def command_prepare_super(args: argparse.Namespace) -> None:
    settings = {"region": args.region, "universe": args.universe, "delay": args.delay, "decay": args.decay, "neutralization": args.neutralization, "truncation": args.truncation, "nan_handling": args.nan_handling}
    database = open_alpha_database(Path(getattr(args, "config", DEFAULT_CONFIG_PATH)))
    try: candidates = prepare_super_candidates(database, settings, max_candidates=args.max_candidates)
    finally: database.close()
    _write_json(Path(args.output), {"settings": settings, "candidates": candidates})
    print(f"super_candidates={len(candidates)} output={args.output}")


def command_simulate_super(args: argparse.Namespace) -> None:
    if not args.execute: raise SystemExit("Refusing to consume BRAIN simulation quota: rerun with --execute.")
    payload = json.loads(Path(args.candidates).read_text(encoding="utf-8")); candidates = payload.get("candidates", payload) if isinstance(payload, dict) else payload
    results = asyncio.run(simulate_super(candidates, args)); _write_json(Path(args.output), {"settings": vars(args), "results": results})
    print(f"super simulation batches={len(results)} output={args.output}")
