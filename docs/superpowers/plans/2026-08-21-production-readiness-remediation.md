# Production Readiness Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real BRAIN research path fail closed, recover stalled batches without duplicate submission, and complete CLI governance with a durable database path.

**Architecture:** Keep `SimulationTracker` as the only source of truth for platform batches. Add a deterministic terminal-state reducer and stale-batch watchdog, then make the CLI delegate final approval to the existing evidence engine using an explicit database path.

**Tech Stack:** Python 3.12, pytest, SQLite/WAL, requests, WorldQuant BRAIN REST gateway.

## Global Constraints

- No automatic Alpha submission; this work may only poll, classify, or mark candidates.
- A platform Location is immutable: a stalled batch is polled or escalated, never reposted.
- Only `submission_ready` evidence may enter the submission registry.
- Preserve existing user changes outside the named files.

---

### Task 1: Make terminal child failures visible to the tracker

**Files:**
- Modify: `alpha_operator_framework/platform/simulation_tracker.py`
- Test: `tests/test_storage_concurrency.py`

- [ ] Add a failing test with a child payload `{"status": "ERROR", "message": "invalid EVENT input"}` and assert its result row becomes `failed` with the message.
- [ ] Run `pytest tests/test_storage_concurrency.py -q`; expected: failure because the tracker records every child without `alpha` as `running`.
- [ ] In `SimulationTracker.poll`, map child terminal statuses `ERROR`, `FAILED`, and `CANCELLED` to `record_simulation_result(..., status="failed", error_message=...)`; retain `running` only for non-terminal children.
- [ ] Re-run the same test; expected: pass.

### Task 2: Add a non-resubmitting stale-batch watchdog

**Files:**
- Modify: `alpha_operator_framework/platform/simulation_tracker.py`
- Modify: `alpha_machine.py`
- Test: `tests/test_storage_concurrency.py`

- [ ] Add a failing test for a batch whose `last_polled_at` exceeds a supplied TTL and assert the batch is marked `stalled` without invoking `submit_request`.
- [ ] Run the focused test and verify the expected failure.
- [ ] Implement `SimulationTracker.mark_stalled_if_expired(batch_id, max_idle_seconds, now=None)`; it records `stalled` and a diagnostic message, and never calls `submit_request`.
- [ ] Add `alpha_machine.py poll-simulation --stale-after-seconds` support that runs the watchdog after polling.
- [ ] Re-run the focused tests; expected: pass.

### Task 3: Repair the CLI database path and make its governance fail closed

**Files:**
- Modify: `alpha_operator_framework/orchestrator.py`
- Test: `tests/test_framework.py`

- [ ] Add a failing test that invokes `cmd_submit` with `execute=True` and a `database` attribute, then asserts no `args.db` access occurs and a candidate lacking OOS evidence remains non-ready.
- [ ] Run the focused test and verify the expected `AttributeError`/incorrect behavior.
- [ ] Replace `args.db` with `getattr(args, "database", "data/alpha_research.db")`; include the same `database` in `cmd_run_all`'s `submit_args`.
- [ ] Make the CLI call `DecisionApprovalEngine` with `EvidenceLevel.PLATFORM_IS` only as a fail-closed precheck; it must never mark `submission_ready` unless an explicit locked-OOS record is present.
- [ ] Re-run the focused test; expected: pass.

### Task 4: Verify the production operating path

**Files:**
- Test: `tests/test_recovery_drill.py`
- Test: `tests/test_auto_pilot.py`

- [ ] Add a recovery test that persists an accepted batch, recreates the tracker, and verifies it polls the stored Location rather than submitting a new location.
- [ ] Run each new test before its implementation and observe the expected failure.
- [ ] Run `pytest tests/test_storage_concurrency.py tests/test_framework.py tests/test_recovery_drill.py tests/test_auto_pilot.py -q`; expected: all pass.
- [ ] Run `git diff --check`; expected: no whitespace errors.

## Self-review

- Scope covers the three P0/P1 production blockers: child status reduction, stalled-batch handling, and executable final governance.
- The plan deliberately excludes automatic Alpha submission, scheduling infrastructure, and unrelated refactors.
