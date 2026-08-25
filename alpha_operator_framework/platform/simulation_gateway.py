"""Completion-aware adapter for workflow simulation submissions."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Sequence

from alpha_operator_framework.cli.simulation import (
    DEFAULT_CONFIG_PATH,
    poll_simulation_batch,
    simulate as submit_simulation,
)


_sleep = asyncio.sleep
_monotonic = time.monotonic
_TERMINAL_STATUSES = frozenset({"completed", "failed", "stalled", "cancelled"})


async def simulate(
    tasks: Sequence[dict[str, Any]],
    args: Any,
    *,
    wait_for_completion: bool = False,
    poll_interval: float = 5.0,
    max_wait_seconds: float = 600.0,
) -> list[dict[str, Any]]:
    """Submit tasks and optionally return their durable terminal result rows."""
    submitted = await submit_simulation(tasks, args)
    if not wait_for_completion:
        return submitted

    config_path = Path(getattr(args, "config", None) or DEFAULT_CONFIG_PATH)
    completed: list[dict[str, Any]] = []
    for submission in submitted:
        batch_id = submission.get("simulation_batch_id")
        if batch_id is None:
            completed.append(dict(submission))
            continue
        completed.extend(await _poll_until_terminal(
            int(batch_id), config_path, poll_interval=poll_interval, max_wait_seconds=max_wait_seconds,
        ))
    return completed


async def _poll_until_terminal(
    batch_id: int,
    config_path: Path,
    *,
    poll_interval: float,
    max_wait_seconds: float,
) -> list[dict[str, Any]]:
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")
    if max_wait_seconds <= 0:
        raise ValueError("max_wait_seconds must be positive")

    deadline = _monotonic() + max_wait_seconds
    while True:
        payload = await poll_simulation_batch(batch_id, config_path)
        batch = payload["batch"]
        if str(batch.get("status") or "").lower() in _TERMINAL_STATUSES:
            return [_usable_result_row(row) for row in payload["results"]]
        remaining = deadline - _monotonic()
        if remaining <= 0:
            raise TimeoutError(f"simulation batch {batch_id} did not reach a terminal state within {max_wait_seconds}s")
        await _sleep(min(poll_interval, remaining))


def _usable_result_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decode persisted result JSON and expose in-sample metrics at the top level."""
    result = dict(row)
    raw_details = result.get("result_json")
    if isinstance(raw_details, str):
        try:
            raw_details = json.loads(raw_details)
        except json.JSONDecodeError:
            raw_details = None
    if isinstance(raw_details, dict):
        result["result_json"] = raw_details
        metrics = raw_details.get("is")
        if isinstance(metrics, dict):
            for name, value in metrics.items():
                result.setdefault(name, value)
    return result


__all__ = ["simulate"]
