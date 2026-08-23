"""Idempotent retry worker tests."""

from alpha_operator_framework.infrastructure.retry import RetryWorker


def test_retry_worker_never_exceeds_attempt_limit_for_same_key() -> None:
    attempts = []
    worker = RetryWorker(max_attempts=2)

    worker.run("batch:0", lambda: attempts.append("run") or False)
    worker.run("batch:0", lambda: attempts.append("run") or False)
    accepted = worker.run("batch:0", lambda: attempts.append("run") or True)

    assert attempts == ["run", "run"]
    assert accepted is False
