"""Regular simulation command adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Sequence

from alpha_operator_framework.infrastructure.maintenance import open_alpha_database
from alpha_operator_framework.platform.simulation_tracker import SimulationTracker

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"
)


def normalize_platform_url(base_url: str, location: str) -> str:
    if location.startswith(("http://", "https://")):
        return location
    return (
        f"{base_url}{location}"
        if location.startswith("/simulations/")
        else f"{base_url}/simulations/{location}"
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _platform_tracker(database: Any, *, submit: Any) -> SimulationTracker:
    from cnhkmcp.untracked.platform_functions import brain_client

    def fetch(location: str) -> tuple[dict[str, Any], float]:
        response = brain_client.session.get(
            normalize_platform_url(brain_client.base_url, location)
        )
        response.raise_for_status()
        return response.json() if response.text else {}, float(
            response.headers.get("Retry-After", 0)
        )

    def detail(alpha_id: str) -> dict[str, Any]:
        response = brain_client.session.get(
            f"{brain_client.base_url}/alphas/{alpha_id}"
        )
        response.raise_for_status()
        return response.json()

    return SimulationTracker(database, submit=submit, fetch=fetch, detail=detail)


async def simulate(
    tasks: Sequence[dict[str, Any]], args: argparse.Namespace
) -> list[dict[str, Any]]:
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    results: list[dict[str, Any]] = []
    by_decay: dict[float, list[dict[str, Any]]] = {}
    for task in tasks:
        by_decay.setdefault(float(task["decay"]), []).append(task)
    for decay, items in by_decay.items():
        for start in range(0, len(items), args.batch_size):
            batch = items[start : start + args.batch_size]
            if len(batch) < 2:
                results.extend(
                    {**task, "status": "PENDING_NEEDS_PAIR"} for task in batch
                )
                continue
            settings = {
                "region": args.region,
                "universe": args.universe,
                "delay": args.delay,
                "decay": decay,
                "neutralization": args.neutralization,
                "truncation": args.truncation,
                "nan_handling": args.nan_handling,
                "test_period": args.test_period,
            }
            database = open_alpha_database(
                Path(getattr(args, "config", DEFAULT_CONFIG_PATH))
            )
            try:

                def submit(batch_tasks: list[dict[str, Any]]) -> str:
                    payload = [
                        {
                            "type": "REGULAR",
                            "settings": {
                                "instrumentType": "EQUITY",
                                "region": args.region,
                                "universe": args.universe,
                                "delay": args.delay,
                                "decay": decay,
                                "neutralization": args.neutralization,
                                "truncation": args.truncation,
                                "pasteurization": "ON",
                                "unitHandling": "VERIFY",
                                "nanHandling": args.nan_handling,
                                "language": "FASTEXPR",
                                "visualization": False,
                                "testPeriod": args.test_period,
                                "maxTrade": "OFF",
                            },
                            "regular": task["expression"],
                        }
                        for task in batch_tasks
                    ]
                    response = brain_client.session.post(
                        f"{brain_client.base_url}/simulations", json=payload
                    )
                    response.raise_for_status()
                    location = response.headers.get("Location")
                    if not location:
                        raise RuntimeError(
                            "platform did not return a simulation Location"
                        )
                    return location

                batch_id = _platform_tracker(database, submit=submit).submit(
                    batch, settings
                )
                results.append(
                    {
                        "simulation_batch_id": batch_id,
                        "status": "submitted",
                        "requested_count": len(batch),
                    }
                )
            finally:
                database.close()
    return results


async def poll_simulation_batch(batch_id: int, config_path: Path) -> dict[str, Any]:
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    database = open_alpha_database(config_path)
    try:
        batch = _platform_tracker(database, submit=lambda _: "").poll(batch_id)
        return {"batch": batch, "results": database.get_simulation_results(batch_id)}
    finally:
        database.close()


def command_simulate(args: argparse.Namespace) -> None:
    if not args.execute:
        raise SystemExit(
            "Refusing to consume BRAIN simulation quota: rerun with --execute."
        )
    payload = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload
    results = asyncio.run(simulate(tasks, args))
    _write_json(Path(args.output), {"settings": vars(args), "results": results})
    print(f"simulation batches={len(results)} output={args.output}")


def command_poll_simulation(args: argparse.Namespace) -> None:
    payload = asyncio.run(
        poll_simulation_batch(
            args.batch_id, Path(getattr(args, "config", DEFAULT_CONFIG_PATH))
        )
    )
    _write_json(Path(args.output), payload)
    batch = payload["batch"]
    print(
        f"batch={args.batch_id} status={batch['status']} completed={batch['completed_count']} failed={batch['failed_count']}"
    )
