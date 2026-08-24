"""Durable, fail-closed submission outbox."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Mapping

from sqlalchemy import Engine, func, insert, select, update

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


class SqlAlchemySubmissionOutbox:
    """Database-neutral outbox used by the configured research runtime."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        from alpha_operator_framework.infrastructure.sqlalchemy_migrations import submission_outbox

        self.table = submission_outbox

    def pending(self, limit: int = 100) -> list[SubmissionReceipt]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.table.c.platform_alpha_id, self.table.c.expression).where(
                self.table.c.status == "PENDING").order_by(self.table.c.platform_alpha_id).limit(limit)).all()
        return [SubmissionReceipt(*row) for row in rows]

    def claim_pending(self, limit: int = 100, lease_seconds: int = 300) -> list[SubmissionReceipt]:
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self.engine.begin() as connection:
            connection.execute(update(self.table).where(
                self.table.c.status == "DISPATCHING",
                (self.table.c.lease_until.is_(None)) | (self.table.c.lease_until <= now.isoformat()),
            ).values(status="PENDING", lease_until=None))
            rows = connection.execute(select(self.table.c.platform_alpha_id, self.table.c.expression).where(
                self.table.c.status == "PENDING").order_by(self.table.c.platform_alpha_id).limit(limit)).all()
            claimed = []
            for row in rows:
                result = connection.execute(update(self.table).where(
                    self.table.c.platform_alpha_id == row.platform_alpha_id, self.table.c.status == "PENDING",
                ).values(status="DISPATCHING", lease_until=lease_until))
                if result.rowcount:
                    claimed.append(SubmissionReceipt(*row))
        return claimed

    def mark_submitted(self, receipt: SubmissionReceipt) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(self.table).where(self.table.c.platform_alpha_id == receipt.platform_alpha_id).values(
                status="SUBMITTED", lease_until=None))

    def record_failure(self, receipt: SubmissionReceipt, error: Exception, max_attempts: int) -> None:
        with self.engine.begin() as connection:
            row = connection.execute(select(self.table.c.attempts).where(
                self.table.c.platform_alpha_id == receipt.platform_alpha_id)).one()
            attempts = row.attempts + 1
            connection.execute(update(self.table).where(self.table.c.platform_alpha_id == receipt.platform_alpha_id).values(
                attempts=attempts, last_error=str(error)[:1000], lease_until=None,
                status="PENDING" if attempts < max_attempts else "FAILED"))

    def status_of(self, platform_alpha_id: str) -> tuple[str, int, str | None]:
        with self.engine.connect() as connection:
            row = connection.execute(select(self.table.c.status, self.table.c.attempts, self.table.c.last_error).where(
                self.table.c.platform_alpha_id == platform_alpha_id)).one_or_none()
        if row is None:
            raise KeyError(platform_alpha_id)
        return row.status, row.attempts, row.last_error

    def status_counts(self) -> dict[str, int]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.table.c.status, func.count()).group_by(self.table.c.status)).all()
        return {str(status): int(count) for status, count in rows}

    def enqueue(self, case: SubmissionCase) -> SubmissionReceipt:
        approval = case.approve()
        if not approval.is_approved:
            raise ValueError(f"Submission case is not approved: {approval.reason}")
        alpha_id = case.result.platform_alpha_id
        assert alpha_id is not None
        with self.engine.begin() as connection:
            exists = connection.execute(select(self.table.c.platform_alpha_id).where(
                self.table.c.platform_alpha_id == alpha_id)).scalar_one_or_none()
            if exists is None:
                connection.execute(insert(self.table).values(
                    platform_alpha_id=alpha_id, expression=case.result.expression, status="PENDING", attempts=0))
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
        outbox: Any,
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
