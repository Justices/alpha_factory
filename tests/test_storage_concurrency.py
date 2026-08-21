"""Concurrency and storage architecture stress tests for SQLite WAL and DatabaseConnectionManager."""

import concurrent.futures
import tempfile
import threading
import time
from pathlib import Path

import pytest

from alpha_operator_framework.database import AlphaDatabase, DatabaseConnectionManager
from alpha_operator_framework.platform.simulation_tracker import SimulationTracker


def test_database_wal_mode_and_pragmas():
    """Verify that SQLite connection manager correctly configures WAL mode and pragmas."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_wal.db"
        mgr = DatabaseConnectionManager(db_path, wal_mode=True)
        try:
            conn = mgr.get_connection()
            cur = conn.cursor()

            # 1. Journal mode must be WAL
            cur.execute("PRAGMA journal_mode;")
            journal_mode = cur.fetchone()[0].lower()
            assert journal_mode == "wal"

            # 2. Busy timeout must be positive (30s = 30000ms)
            cur.execute("PRAGMA busy_timeout;")
            busy_timeout = cur.fetchone()[0]
            assert busy_timeout >= 10000

            # 3. Synchronous mode must be NORMAL (1)
            cur.execute("PRAGMA synchronous;")
            sync_mode = cur.fetchone()[0]
            assert sync_mode == 1  # 1 = NORMAL
        finally:
            mgr.close_all()


def test_database_transaction_rollback():
    """Verify that transaction() automatically rolls back changes when exception occurs."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "test_rollback.db")
        try:
            # 1. Successful commit
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO alpha_expressions (expression_sha, expression, settings, created_at, updated_at) "
                    "VALUES ('sha1', 'close', '{}', '2025-01-01', '2025-01-01')"
                )

            assert db.get_expression_by_sha("sha1") is not None

            # 2. Failed transaction with rollback
            with pytest.raises(ValueError):
                with db.transaction() as conn:
                    conn.execute(
                        "INSERT INTO alpha_expressions (expression_sha, expression, settings, created_at, updated_at) "
                        "VALUES ('sha2', 'volume', '{}', '2025-01-01', '2025-01-01')"
                    )
                    raise ValueError("Simulated failure inside transaction")

            # sha2 should NOT be present in database
            assert db.get_expression_by_sha("sha2") is None
        finally:
            db.close()


def test_multithreaded_concurrent_read_write():
    """Stress test: 8 threads concurrently writing and querying AlphaDatabase without locking errors."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_concurrent.db"
        db = AlphaDatabase(db_path, timeout=30.0, wal_mode=True)

        n_threads = 8
        items_per_thread = 25
        errors = []

        def worker_task(thread_id: int):
            try:
                for i in range(items_per_thread):
                    expr = f"rank(close_{thread_id}_{i})"
                    # Write
                    exp_id = db.insert_expression(expr, {"region": "USA"})
                    assert exp_id is not None
                    sha = db.compute_sha(expr)
                    # Read
                    found = db.get_expression_by_sha(sha)
                    assert found is not None
                    assert found.expression == expr
            except Exception as e:
                errors.append(e)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
                futures = [executor.submit(worker_task, tid) for tid in range(n_threads)]
                concurrent.futures.wait(futures)

            assert len(errors) == 0, f"Concurrent workers encountered errors: {errors}"
        finally:
            db.close()


def test_tracker_records_terminal_child_error_as_failed(tmp_path):
    """A platform child in ERROR must not remain forever in the running state."""
    db = AlphaDatabase(tmp_path / "tracker_error.db")
    try:
        def fetch(location):
            if location == "batch-location":
                return {"children": ["child-location"], "status": "ERROR"}, 0.0
            return {"status": "ERROR", "message": "EVENT input requires vec_avg"}, 0.0

        tracker = SimulationTracker(
            db,
            submit=lambda tasks: "batch-location",
            fetch=fetch,
            detail=lambda alpha_id: {},
        )
        batch_id = tracker.submit(
            [{"expression": "ts_delta(event_field, 20)", "decay": 6}],
            {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 6},
        )

        tracker.poll(batch_id)

        result = db.get_simulation_results(batch_id)[0]
        assert result["status"] == "failed"
        assert "vec_avg" in result["error_message"]
    finally:
        db.close()


def test_tracker_marks_idle_batch_stalled_without_resubmitting(tmp_path):
    """An idle platform Location is escalated locally and is never submitted again."""
    db = AlphaDatabase(tmp_path / "tracker_stalled.db")
    submissions = []
    try:
        tracker = SimulationTracker(
            db,
            submit=lambda tasks: submissions.append(tasks) or "batch-location",
            fetch=lambda location: ({"progress": 0.35}, 0.0),
            detail=lambda alpha_id: {},
        )
        batch_id = tracker.submit(
            [{"expression": "rank(close)", "decay": 6}],
            {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 6},
        )
        db._get_connection().execute(
            "UPDATE simulation_batches SET last_polled_at='2000-01-01T00:00:00' WHERE id=?", (batch_id,)
        )
        db._get_connection().commit()

        assert tracker.mark_stalled_if_expired(batch_id, max_idle_seconds=60, now="2000-01-01T00:02:00") is True

        batch = db.get_simulation_batch(batch_id)
        assert batch["status"] == "stalled"
        assert len(submissions) == 1
    finally:
        db.close()
