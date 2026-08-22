"""Durable, fail-closed submission outbox."""

from __future__ import annotations

import sqlite3
import asyncio
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from alpha_operator_framework.knowledge.submission import SubmissionCase


class SubmissionNotAvailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmissionReceipt:
    platform_alpha_id: str
    expression: str


class SqliteSubmissionOutbox:
    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS submission_outbox "
                "(platform_alpha_id TEXT PRIMARY KEY, expression TEXT NOT NULL, status TEXT NOT NULL)"
            )

    def enqueue(self, case: SubmissionCase) -> SubmissionReceipt:
        approval = case.approve()
        if not approval.is_approved:
            raise ValueError(f"Submission case is not approved: {approval.reason}")
        alpha_id = case.result.platform_alpha_id
        assert alpha_id is not None
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO submission_outbox(platform_alpha_id, expression, status) VALUES (?, ?, 'PENDING')",
                (alpha_id, case.result.expression),
            )
        return SubmissionReceipt(alpha_id, case.result.expression)

    def dispatch(self, receipt: SubmissionReceipt) -> None:
        raise SubmissionNotAvailable("Real platform submission adapter is not enabled")


class CnhkMcpSubmissionGateway:
    """Production adapter; vendor dependency is resolved only at dispatch time."""

    def __init__(self, submit: Callable[[str], Any] | None = None) -> None:
        self._submit = submit

    def dispatch(self, receipt: SubmissionReceipt) -> Any:
        submit = self._submit
        if submit is None:
            try:
                from cnhkmcp.untracked.platform import submit_alpha
            except ImportError:
                try:
                    from cnhkmcp.untracked.platform_functions import submit_alpha
                except ImportError as error:
                    raise SubmissionNotAvailable("cnhkmcp vendor dependency is unavailable") from error
            submit = submit_alpha
        result = submit(receipt.platform_alpha_id)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
