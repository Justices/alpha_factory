"""Completion semantics for the workflow simulation gateway."""

from __future__ import annotations

import asyncio
import ast
import json
from argparse import Namespace
from pathlib import Path


def test_workflow_call_sites_request_completed_simulations() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "alpha_operator_framework/workflow/branches.py",
        "alpha_operator_framework/workflow/survey.py",
        "alpha_operator_framework/orchestration/survey.py",
        "alpha_operator_framework/orchestration/deepen.py",
    ):
        tree = ast.parse((root / relative_path).read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "simulate"
        ]
        assert calls, relative_path
        assert all(
            any(keyword.arg == "wait_for_completion" and keyword.value.value is True
                for keyword in call.keywords
                if isinstance(keyword.value, ast.Constant))
            for call in calls
        ), relative_path


def test_waiting_for_completion_polls_to_terminal_and_returns_metrics(monkeypatch) -> None:
    from alpha_operator_framework.platform import simulation_gateway as gateway

    submitted = [{"simulation_batch_id": 7, "status": "submitted", "requested_count": 2}]
    polls = iter([
        {"batch": {"id": 7, "status": "running"}, "results": []},
        {"batch": {"id": 7, "status": "completed"}, "results": [{
            "expression": "rank(close)", "alpha_id": "alpha-7", "status": "completed",
            "result_json": json.dumps({"is": {"sharpe": 1.7, "fitness": 1.1}}),
        }]},
    ])
    sleeps: list[float] = []

    async def submit(tasks, args):
        assert tasks == [{"expression": "rank(close)", "decay": 4}]
        assert args.region == "GBR"
        return submitted

    async def poll(batch_id, config_path):
        assert batch_id == 7
        return next(polls)

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(gateway, "submit_simulation", submit)
    monkeypatch.setattr(gateway, "poll_simulation_batch", poll)
    monkeypatch.setattr(gateway, "_sleep", sleep)

    rows = asyncio.run(gateway.simulate(
        [{"expression": "rank(close)", "decay": 4}],
        Namespace(region="GBR"),
        wait_for_completion=True,
        poll_interval=0.01,
        max_wait_seconds=1,
    ))

    assert sleeps == [0.01]
    assert rows == [{
        "expression": "rank(close)", "alpha_id": "alpha-7", "status": "completed",
        "result_json": {"is": {"sharpe": 1.7, "fitness": 1.1}}, "sharpe": 1.7, "fitness": 1.1,
    }]


def test_without_completion_preserves_submission_rows(monkeypatch) -> None:
    from alpha_operator_framework.platform import simulation_gateway as gateway

    async def submit(tasks, args):
        return [{"simulation_batch_id": 3, "status": "submitted"}]

    monkeypatch.setattr(gateway, "submit_simulation", submit)
    rows = asyncio.run(gateway.simulate([], Namespace(), wait_for_completion=False))

    assert rows == [{"simulation_batch_id": 3, "status": "submitted"}]
