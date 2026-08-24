"""Durable, fail-closed submission outbox."""

from __future__ import annotations

import sqlite3
import asyncio
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from alpha_operator_framework.knowledge.submission import SubmissionCase, SubmissionEvidence


class SubmissionNotAvailable(RuntimeError):
    pass


class ConfiguredSubmissionEvidenceGateway:
    """Turns externally verified, versioned evidence records into approval evidence."""

    def __init__(self, records: Mapping[str, Mapping[str, Any]], authorized: bool) -> None:
        self.records = records
        self.authorized = authorized

    def evidence_for(self, result: Any) -> SubmissionEvidence:
        record = self.records.get(result.platform_alpha_id or "", {})
        verified = self._valid_record(record)
        return SubmissionEvidence(
            correlation_checked=bool(record.get("correlation_checked", False)),
            capacity_checked=bool(record.get("capacity_checked", False)),
            lineage_verified=bool(record.get("lineage_verified", False)),
            authorized=self.authorized,
            record_verified=verified,
        )

    @staticmethod
    def _valid_record(record: Mapping[str, Any]) -> bool:
        required = ("source", "verified_at", "expires_at", "receipt_ref", "summary")
        if not all(isinstance(record.get(key), str) and record[key].strip() for key in required):
            return False
        try:
            verified_at = datetime.fromisoformat(record["verified_at"])
            expires_at = datetime.fromisoformat(record["expires_at"])
        except ValueError:
            return False
        if verified_at.tzinfo is None or expires_at.tzinfo is None:
            return False
        return verified_at <= datetime.now(UTC) < expires_at


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
                "(platform_alpha_id TEXT PRIMARY KEY, expression TEXT NOT NULL, status TEXT NOT NULL, "
                "attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, lease_until TEXT)"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(submission_outbox)")}
            if "attempts" not in columns:
                connection.execute("ALTER TABLE submission_outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "last_error" not in columns:
                connection.execute("ALTER TABLE submission_outbox ADD COLUMN last_error TEXT")
            if "lease_until" not in columns:
                connection.execute("ALTER TABLE submission_outbox ADD COLUMN lease_until TEXT")

    def pending(self, limit: int = 100) -> list[SubmissionReceipt]:
        """Read, but do not claim, submissions awaiting a dedicated dispatch worker."""
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT platform_alpha_id, expression FROM submission_outbox "
                "WHERE status = 'PENDING' ORDER BY platform_alpha_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [SubmissionReceipt(*row) for row in rows]

    def claim_pending(self, limit: int = 100, lease_seconds: int = 300) -> list[SubmissionReceipt]:
        """Atomically lease pending rows so concurrent workers cannot dispatch them twice."""
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        now_text = now.isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE submission_outbox SET status = 'PENDING', lease_until = NULL "
                "WHERE status = 'DISPATCHING' AND (lease_until IS NULL OR lease_until <= ?)",
                (now_text,),
            )
            rows = connection.execute(
                "SELECT platform_alpha_id, expression FROM submission_outbox "
                "WHERE status = 'PENDING' ORDER BY platform_alpha_id LIMIT ?",
                (limit,),
            ).fetchall()
            connection.executemany(
                "UPDATE submission_outbox SET status = 'DISPATCHING', lease_until = ? "
                "WHERE platform_alpha_id = ? AND status = 'PENDING'",
                [(lease_until, row[0]) for row in rows],
            )
        return [SubmissionReceipt(*row) for row in rows]

    def mark_submitted(self, receipt: SubmissionReceipt) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE submission_outbox SET status = 'SUBMITTED', lease_until = NULL WHERE platform_alpha_id = ?",
                (receipt.platform_alpha_id,),
            )

    def record_failure(self, receipt: SubmissionReceipt, error: Exception, max_attempts: int) -> None:
        """Keep a transient failure pending until its bounded retry budget is exhausted."""
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE submission_outbox SET attempts = attempts + 1, last_error = ?, lease_until = NULL, "
                "status = CASE WHEN attempts + 1 < ? THEN 'PENDING' ELSE 'FAILED' END "
                "WHERE platform_alpha_id = ?",
                (str(error)[:1000], max_attempts, receipt.platform_alpha_id),
            )

    def status_of(self, platform_alpha_id: str) -> tuple[str, int, str | None]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT status, attempts, last_error FROM submission_outbox WHERE platform_alpha_id = ?",
                (platform_alpha_id,),
            ).fetchone()
        if row is None:
            raise KeyError(platform_alpha_id)
        return row[0], row[1], row[2]

    def status_counts(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) FROM submission_outbox GROUP BY status"
            ).fetchall()
        return {status: count for status, count in rows}

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


class SubmissionOutboxWorker:
    """Explicit submission boundary; research execution only ever enqueues approved cases."""

    def __init__(
        self,
        outbox: SqliteSubmissionOutbox,
        gateway: CnhkMcpSubmissionGateway,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.outbox = outbox
        self.gateway = gateway
        self.max_attempts = max_attempts

    def process_pending(self, limit: int = 100) -> list[SubmissionReceipt]:
        dispatched: list[SubmissionReceipt] = []
        for receipt in self.outbox.claim_pending(limit):
            try:
                self.gateway.dispatch(receipt)
            except Exception as error:
                self.outbox.record_failure(receipt, error, self.max_attempts)
                continue
            self.outbox.mark_submitted(receipt)
            dispatched.append(receipt)
        return dispatched
